#!/usr/bin/env bash
set -e

if [[ -n ${LOG_LEVEL} ]]; then
  sed 's/\(^.\+"level":\s*"\).\+\(".*$\)/\1'$LOG_LEVEL'\2/g' -i /etc/$COMPANY_NAME/documentserver/log4js/production.json
fi

if [[ -n ${LOG_TYPE} ]]; then
  sed 's/\("type"\:\) "pattern"/\1 "'$LOG_TYPE'"/' -i /etc/$COMPANY_NAME/documentserver/log4js/production.json
fi

if [[ -n ${LOG_PATTERN} ]]; then
  sed "s/\(\"pattern\"\:\).*/\1 \"$LOG_PATTERN\"/" -i /etc/$COMPANY_NAME/documentserver/log4js/production.json
fi

ACTIVEMQ_TRANSPORT=""
case $AMQP_PROTO in
  amqps | amqp+ssl)
    ACTIVEMQ_TRANSPORT="tls"
    ;;
  *)
    ACTIVEMQ_TRANSPORT="tcp"
    ;;
esac

if [[ -n "$REDIS_SENTINEL_NODES" ]]; then
  declare -a REDIS_SENTINEL_NODES_ALL=($REDIS_SENTINEL_NODES)
  REDIS_SENTINEL_NODES_ARRAY=()
  for node in "${REDIS_SENTINEL_NODES_ALL[@]}"; do
    host="${node%%:*}"
    port="${node##*:}"
    REDIS_SENTINEL_NODES_ARRAY+=('{ "host": "'$host'", "port": '$port' }')
  done
  OLD_IFS="$IFS"
  IFS=","
  NODES=$(echo "${REDIS_SENTINEL_NODES_ARRAY[*]}")
  IFS="$OLD_IFS"
  REDIS_SENTINEL='[ '$NODES' ],'
else
  REDIS_SENTINEL='[ { "host": "'${REDIS_SERVER_HOST:-localhost}'", "port": '${REDIS_SERVER_PORT:-6379}' } ],'
fi

if [[ -n "$REDIS_CLUSTER_NODES" ]]; then
  declare -a REDIS_CLUSTER_NODES_ALL=($REDIS_CLUSTER_NODES)
  REDIS_CLUSTER_NODES_ARRAY=()
  for node in "${REDIS_CLUSTER_NODES_ALL[@]}"; do
    REDIS_CLUSTER_NODES_ARRAY+=('{ "url": "redis://'$node'" }')
  done
  OLD_IFS="$IFS"
  IFS=","
  NODES=$(echo "${REDIS_CLUSTER_NODES_ARRAY[*]}")
  IFS="$OLD_IFS"
  REDIS_CLUSTER='"rootNodes": [ '$NODES' ], "defaults": { "username": "'${REDIS_SERVER_USER:-default}'", "password": "'$REDIS_SERVER_PWD'" }'
else
  REDIS_CLUSTER=''
fi

export NODE_CONFIG='{
  "statsd": {
    "useMetrics": '${METRICS_ENABLED:-false}',
    "host": "'${METRICS_HOST:-localhost}'",
    "port": '${METRICS_PORT:-8125}',
    "prefix": "'${METRICS_PREFIX:-ds.}'"
  },
  "runtimeConfig": {
    "filePath": "/var/www/'${COMPANY_NAME}'/config/runtime.json"
  },
  "services": {
    "CoAuthoring": {
      "sql": {
        "type": "'${DB_TYPE:-postgres}'",
        "dbHost": "'${DB_HOST:-localhost}'",
        "dbPort": '${DB_PORT:-5432}',
        "dbUser": "'${DB_USER:=onlyoffice}'",
        "dbName": "'${DB_NAME:-${DB_USER}}'",
        "dbPass": "'${DB_PWD:-onlyoffice}'"
      },
      "redis": {
        "name": "'${REDIS_CONNECTOR_NAME:-redis}'",
        "host": "'${REDIS_SERVER_HOST:-${REDIST_SERVER_HOST:-localhost}}'",
        "port": '${REDIS_SERVER_PORT:-${REDIST_SERVER_PORT:-6379}}',
        "options": {
          "user": "'${REDIS_SERVER_USER:-default}'",
          "password": "'${REDIS_SERVER_PWD}'",
          "db": "'${REDIS_SERVER_DB_NUM:-0}'"
        },
        "optionsCluster": { '${REDIS_CLUSTER}' },
        "iooptions": {
          "sentinels": '${REDIS_SENTINEL}'
          "name": "'${REDIS_SENTINEL_GROUP_NAME:-mymaster}'",
          "sentinelPassword": "'${REDIS_SENTINEL_PWD}'",
          "username": "'${REDIS_SERVER_USER:-default}'",
          "password": "'${REDIS_SERVER_PWD}'",
          "db": "'${REDIS_SERVER_DB_NUM:-0}'"
        }
      },
      "token": {
        "enable": {
          "browser": '${JWT_ENABLED:=true}',
          "request": {
            "inbox": '${JWT_ENABLED_INBOX:-${JWT_ENABLED}}',
            "outbox": '${JWT_ENABLED_OUTBOX:-${JWT_ENABLED}}'
          }
        },
        "inbox": {
          "header": "'${JWT_HEADER_INBOX:-${JWT_HEADER:=Authorization}}'",
          "inBody": '${JWT_IN_BODY:=false}'
        },
        "outbox": {
          "header": "'${JWT_HEADER_OUTBOX:-${JWT_HEADER}}'",
          "inBody": '${JWT_IN_BODY}'
        }
      },
      "secret": {
        "inbox": {
          "string": "'${JWT_SECRET_INBOX:-${JWT_SECRET:=secret}}'"
        },
        "outbox": {
          "string": "'${JWT_SECRET_OUTBOX:-${JWT_SECRET}}'"
        },
        "browser": {
          "string": "'${JWT_SECRET}'"
        },
        "session": {
          "string": "'${JWT_SECRET}'"
        }
      },
      "request-filtering-agent" : {
        "allowPrivateIPAddress": '${ALLOW_PRIVATE_IP_ADDRESS:-false}',
        "allowMetaIPAddress": '${ALLOW_META_IP_ADDRESS:-false}',
        "allowIPAddressList": '${ALLOW_IP_ADDRESS_LIST:-[]}',
        "denyIPAddressList": '${DENY_IP_ADDRESS_LIST:-[]}'
      }
    }
  },
  "queue": {
    "type": "'${AMQP_TYPE:=rabbitmq}'"
  },
  "activemq": {
    "connectOptions": {
      "port": "'${AMQP_PORT:=5672}'",
      "host": "'${AMQP_HOST:=localhost}'",
      "username": "'${AMQP_USER:=guest}'",
      "password": "'${AMQP_PWD:=guest}'",
      "transport": "'${ACTIVEMQ_TRANSPORT}'"
    }
  },
  "rabbitmq": {
    "url": "'${AMQP_URI:-${AMQP_PROTO:-amqp}://${AMQP_USER}:${AMQP_PWD}@${AMQP_HOST}:${AMQP_PORT}${AMQP_VHOST:-/}}'"
  },
  "wopi": {
    "enable": '${WOPI_ENABLED:-false}',
    "privateKey": "'${WOPI_PRIVATE_KEY}'",
    "privateKeyOld": "'${WOPI_PRIVATE_KEY_OLD}'",
    "publicKey": "'${WOPI_PUBLIC_KEY}'",
    "publicKeyOld": "'${WOPI_PUBLIC_KEY_OLD}'",
    "modulus": "'${WOPI_MODULUS_KEY}'",
    "modulusOld": "'${WOPI_MODULUS_KEY_OLD}'",
    "exponent": '${WOPI_EXPONENT_KEY:=65537}',
    "exponentOld": '${WOPI_EXPONENT_KEY_OLD:-${WOPI_EXPONENT_KEY}}'
  },
  "FileConverter": {
    "converter": {
        "maxprocesscount": 0.001
    }
  },
  "storage": {
    "fs": {
      "folderPath": "/var/lib/'${COMPANY_NAME}'/documentserver/App_Data/cache/files/'${STORAGE_SUBDIRECTORY_NAME:-latest}'",
      "secretString": "'${SECURE_LINK_SECRET:-verysecretstring}'"
    },
    "storageFolderName": "files/'${STORAGE_SUBDIRECTORY_NAME:-latest}'"
  },
  "persistentStorage": {
    "fs": {
      "folderPath": "/var/lib/'${COMPANY_NAME}'/documentserver/App_Data/cache/files",
      "secretString": "'${SECURE_LINK_SECRET:-verysecretstring}'"
    },
    "storageFolderName": "files"
  }
}'

exec "$@"
