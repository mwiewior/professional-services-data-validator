
# Not yet on ibis 12: the fork's Redshift (getindata/axis#425), Teradata (#426), and the stage-2
# engines Snowflake, Postgres, MySQL and SQL Server, whose DVT backends still use ibis 7 internals
collect_ignore = ["ibis_redshift", "ibis_teradata", "ibis_snowflake", "ibis_postgres"]
