import os
import logging
import requests
import json
import time
from kubernetes import client, config, watch

ep_port = os.environ["SHARD_PORT"]
ep_name = os.environ["DS_EP_NAME"]
field_name = f'metadata.name={ep_name}'
label_endpointslice = f"kubernetes.io/service-name={ep_name}"
deployment_name = os.environ.get('DS_DEPLOYMENT_NAME')
label_pod = os.environ["DS_POD_LABEL"]
log_level = os.environ.get('LOG_LEVEL')

url_sending = 'http://127.0.0.1:8000/configuration'
url_pods_sending = 'http://127.0.0.1:8000/configuration_reserved'

pathNS = '/run/secrets/kubernetes.io/serviceaccount/namespace'

with open(pathNS, "r") as f_ns:
    ns = f_ns.read().strip()


def _get_clients():
    config.load_incluster_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.DiscoveryV1Api()


def init_logger(name):
    logger = logging.getLogger(name)
    formatter = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logger.setLevel(logging.DEBUG)
    stdout = logging.StreamHandler()
    stdout.setFormatter(logging.Formatter(formatter))
    stdout.setLevel(logging.DEBUG)
    logger.addHandler(stdout)
    logger.info('Running the script to get the endpoints of the DocumentServer\n')


def get_deploy_version(apps):
    try:
        containers_list = apps.read_namespaced_deployment(name=deployment_name, namespace=ns)
        image = containers_list.spec.template.spec.containers[1].image
        tag = image.split(":")[1]
        if tag != '':
            return tag
        else:
            return 'none'
    except Exception as msg_read_tag:
        logger_endpoints_ds.error(f'Error reading the tag to the Deployment... {msg_read_tag}')
        return 'none'


def get_pods_index(v1):
    pods_by_name = {}
    pods_list = v1.list_namespaced_pod(namespace=ns, label_selector=label_pod)
    for pod in pods_list.items or []:
        try:
            for cs in pod.status.container_statuses or []:
                if cs.name == "proxy" and cs.ready:
                    pods_by_name[pod.metadata.name] = {
                        "ver": pod.metadata.annotations["ds-ver-hash"],
                        "image": pod.spec.containers[1].image,
                        "ip": pod.status.pod_ip,
                    }
                    break
        except Exception as msg_pod:
            logger_endpoints_ds.error(
                f'Failed to build pod index for {pod.metadata.name} Pod... {msg_pod}'
            )
    return pods_by_name


def get_ep_list(ep_items, pods_by_name, apps):
    ds_ep_list = []
    ds_ep_list_tag = []
    deploy_tag = get_deploy_version(apps)
    for ep_ip in ep_items:
        total_result = {}
        try:
            ip = ep_ip["ip"]
            pod_name = ep_ip["pod_name"]
            pod_data = pods_by_name.get(pod_name)
            if not pod_data:
                logger_endpoints_ds.error(f'Pod "{pod_name}" not found in the Pods list')
                ver_ds = 'none'
                pod_tag = 'none'
            else:
                try:
                    ver_ds = pod_data["ver"]
                except Exception as msg_read_annotation:
                    logger_endpoints_ds.error(
                        f'Error when reading an annotation to the {pod_name} Pod... {msg_read_annotation}'
                    )
                    ver_ds = 'none'
                try:
                    pod_tag = pod_data["image"].split(":")[1]
                except Exception as msg_read_pod_tag:
                    logger_endpoints_ds.error(
                        f'Error when reading the tag in the {pod_name} Pod... {msg_read_pod_tag}'
                    )
                    pod_tag = 'none'
            total_result['address'] = ip
            total_result['port'] = ep_port
            total_result['ver'] = ver_ds
            total_result['tag'] = pod_tag
            if pod_tag != deploy_tag:
                ds_ep_list.append(json.dumps(total_result))
            else:
                ds_ep_list_tag.append(json.dumps(total_result))
        except Exception as msg_url:
            logger_endpoints_ds.error(f'Failed to build a list of endpoints: {ds_ep_list}... {msg_url}')
    if len(ds_ep_list_tag) > 0:
        all_ep = f'{ds_ep_list_tag}'.replace("'", "")
        requests.post(url_sending, data=all_ep)
    else:
        all_ep = f'{ds_ep_list}'.replace("'", "")
        requests.post(url_sending, data=all_ep)


def get_running_pod(pods_by_name):
    ds_ep_list = []
    for pod_name, pod_data in pods_by_name.items():
        try:
            total_result = {
                "address": pod_data["ip"],
                "port": ep_port,
                "ver": pod_data["ver"]
            }
            ds_ep_list.append(json.dumps(total_result))
        except Exception as msg_url:
            logger_endpoints_ds.error(
                f'Failed to build a list of Running {pod_name} Pod: {ds_ep_list}... {msg_url}'
            )
    if not ds_ep_list:
        requests.post(url_pods_sending, data="none")
    else:
        all_ep = f'{ds_ep_list}'.replace("'", "")
        requests.post(url_pods_sending, data=all_ep)


def parse_endpointslices(slice_items, v1, apps):
    result = []
    pods = []
    pods_by_name = get_pods_index(v1)
    for slice_obj in slice_items:
        for addr in slice_obj.endpoints:
            if addr.conditions and addr.conditions.ready is True:
                result.append({
                    "ip": addr.addresses[0],
                    "pod_name": addr.target_ref.name
                })
            if addr.conditions and addr.conditions.serving is True:
                pods.append({
                    "ip": addr.addresses[0],
                    "pod_name": addr.target_ref.name
                })
    if len(result) > 0:
        if log_level == 'DEBUG':
            logger_endpoints_ds.debug(f'EndpointSlice "{ep_name}" received and sent')
        get_ep_list(result, pods_by_name, apps)
    else:
        logger_endpoints_ds.warning('The list of ready Endpoints is empty')
        requests.post(url_sending, data="none")
    if len(pods) > 0:
        if log_level == 'DEBUG':
            logger_endpoints_ds.debug(f'Pods "{label_pod}" received and sent')
        get_running_pod(pods_by_name)
    else:
        logger_endpoints_ds.warning('The list of Serving Pods is empty')
        requests.post(url_pods_sending, data="none")


def parse_endpoints_addresses(addresses, v1, apps):
    result = []
    pods_by_name = get_pods_index(v1)
    for addr in addresses:
        result.append({
            "ip": addr.ip,
            "pod_name": addr.target_ref.name
        })
    get_ep_list(result, pods_by_name, apps)


def get_ds_slices_status():
    while True:
        if log_level == 'DEBUG':
            logger_endpoints_ds.debug(f'The Watch cycle for the "{ep_name}" EndpointSlice is running')
        try:
            v1, apps, disc = _get_clients()
            w = watch.Watch()
            for event in w.stream(disc.list_namespaced_endpoint_slice, namespace=ns, label_selector=label_endpointslice):
                try:
                    ep_list = disc.list_namespaced_endpoint_slice(namespace=ns, label_selector=label_endpointslice)
                    if not ep_list.items:
                        logger_endpoints_ds.warning(f'There are no ready addresses for EndpointSlice "{ep_name}"')
                        requests.post(url_sending, data="none")
                        requests.post(url_pods_sending, data="none")
                    else:
                        parse_endpointslices(ep_list.items, v1, apps)
                except Exception as msg_list_ep:
                    logger_endpoints_ds.error(f'Error when trying to list "{ep_name}" EndpointSlice... {msg_list_ep}')
                    requests.post(url_sending, data="none")
                    logger_endpoints_ds.error(f'Error when trying to list "{label_pod}" Pods... {msg_list_ep}')
                    requests.post(url_pods_sending, data="none")
        except Exception as msg_get_ep:
            err_text = str(msg_get_ep)
            if "Invalid value for `endpoints`, must not be `None`" in err_text:
                logger_endpoints_ds.warning(f'Empty EndpointSlice for "{ep_name}"')
                requests.post(url_sending, data="none")
                requests.post(url_pods_sending, data="none")
                time.sleep(3)
            else:
                logger_endpoints_ds.warning(f'Trying to search "{ep_name}" EndpointSlice... {msg_get_ep}')
                logger_endpoints_ds.warning(f'Trying to search "{label_pod}" Pods... {msg_get_ep}')
                time.sleep(1)
        if log_level == 'DEBUG':
            logger_endpoints_ds.debug(f'The Watch cycle for the "{ep_name}" EndpointSlice is ending')


def get_ds_status():
    while True:
        if log_level == 'DEBUG':
            logger_endpoints_ds.debug(f'The Watch cycle for the "{ep_name}" endpoints is running')
        try:
            v1, apps, disc = _get_clients()
            w = watch.Watch()
            for event in w.stream(v1.list_namespaced_endpoints, namespace=ns, field_selector=field_name):
                try:
                    if event['object'].subsets:
                        ep_ds = event['object'].subsets[0].addresses
                        if not ep_ds:
                            logger_endpoints_ds.warning(f'Empty "{ep_name}" endpoints list')
                            requests.post(url_sending, data="none")
                        else:
                            if log_level == 'DEBUG':
                                logger_endpoints_ds.debug(f'Endpoints "{ep_name}" received and sent')
                            parse_endpoints_addresses(ep_ds, v1, apps)
                    else:
                        logger_endpoints_ds.warning(f'There are no addresses for endpoint "{ep_name}"')
                        requests.post(url_sending, data="none")
                except Exception as msg_list_ep:
                    logger_endpoints_ds.error(f'Error when trying to list "{ep_name}" endpoints... {msg_list_ep}')
                    requests.post(url_sending, data="none")
        except Exception as msg_get_ep:
            logger_endpoints_ds.warning(f'Trying to search "{ep_name}" endpoints... {msg_get_ep}')
            time.sleep(1)
        if log_level == 'DEBUG':
            logger_endpoints_ds.debug(f'The Watch cycle for the "{ep_name}" endpoints is ending')


def _use_endpoint_slices():
    try:
        v1, apps, disc = _get_clients()
        disc.list_namespaced_endpoint_slice(namespace=ns, label_selector=label_endpointslice, _preload_content=False)
    except Exception as msg_get_ep_slices:
        logger_endpoints_ds.warning(f"EndpointSlice API probe failed: {msg_get_ep_slices}")
        get_ds_status()
    else:
        get_ds_slices_status()


init_logger('endpoints')
logger_endpoints_ds = logging.getLogger('endpoints.ds')
_use_endpoint_slices()