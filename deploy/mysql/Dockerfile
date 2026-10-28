FROM mysql:8.4
# 配置 COPY 进镜像而非 bind mount：宿主机（尤其 Docker Desktop/Windows）
# 挂载文件权限为 777，mysqld 会以 world-writable 为由忽略该配置。
COPY conf/nis.cnf /etc/mysql/conf.d/nis.cnf
RUN chmod 644 /etc/mysql/conf.d/nis.cnf
