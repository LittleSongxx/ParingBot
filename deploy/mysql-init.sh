# Sourced by the official MySQL entrypoint on first initialization only.
for identity in app flyway nacos growth canal xxljob; do
  case "$identity" in
    app) secret="$SMARTLECT_MYSQL_PASSWORD" ;;
    flyway) secret="$SMARTLECT_FLYWAY_PASSWORD" ;;
    nacos) secret="$SMARTLECT_NACOS_MYSQL_PASSWORD" ;;
    growth) secret="$SMARTLECT_ASSISTANT_MYSQL_PASSWORD" ;;
    canal) secret="$SMARTLECT_CANAL_MYSQL_PASSWORD" ;;
    xxljob) secret="$SMARTLECT_XXLJOB_MYSQL_PASSWORD" ;;
  esac
  [[ "$secret" =~ ^[a-f0-9]{48}$ ]] || { echo 'Invalid generated Smartlect credential' >&2; exit 1; }
  docker_process_sql <<< "CREATE USER 'smartlect_${identity}'@'%' IDENTIFIED BY '${secret}';"
done
# Canal 只需要复制流读取权（binlog 订阅），不给任何业务库读写。
docker_process_sql <<< "GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'smartlect_canal'@'%';"
for domain in admin user product stock cart order pay coupon nacos growth xxljob; do
  docker_process_sql <<< "CREATE DATABASE smartlect_${domain} CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
  case "$domain" in
    nacos|growth|xxljob)
      docker_process_sql <<< "GRANT ALL ON smartlect_${domain}.* TO 'smartlect_${domain}'@'%';" ;;
    *)
      docker_process_sql <<< "GRANT SELECT, INSERT, UPDATE, DELETE ON smartlect_${domain}.* TO 'smartlect_app'@'%';"
      docker_process_sql <<< "GRANT ALL ON smartlect_${domain}.* TO 'smartlect_flyway'@'%';" ;;
  esac
done
unset identity secret domain
