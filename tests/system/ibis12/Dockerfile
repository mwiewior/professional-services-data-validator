# The runner of DVT's ibis 12 engine system tests (tests/system/ibis12): DVT with the drivers
# its engines need, the fork's source mounted at /src at run time.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config curl gnupg ca-certificates \
        default-libmysqlclient-dev libpq-dev unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*
COPY . /src
RUN pip install --no-cache-dir -e "/src[mssql,mysql,trino,clickhouse,develop]" oracledb
WORKDIR /src
