import os

import pandas as pd
import prestodb

from wmfdata.utils import (
    check_kerberos_auth,
    ensure_list
)

def run(commands, catalog="analytics_hive"):
    """
    Runs one or more SQL commands using the Presto SQL engine and returns the last result
    in a Pandas DataFrame.
    
    Presto can be connected to many different backend data stores, or catalogs.
    Currently it is only connected to the Data Lake, with has the catalog name "analytics_hive".

    """
    commands = ensure_list(commands)
    check_kerberos_auth()

    USER_NAME = os.getenv("USER")
    PRESTO_AUTH = prestodb.auth.KerberosAuthentication(
        config="/etc/krb5.conf",
        service_name="presto",
        principal=f"{USER_NAME}@WIKIMEDIA",
        ca_bundle="/etc/ssl/certs/Puppet_Internal_CA.pem"
    )

    connection = prestodb.dbapi.connect(
        catalog=catalog,
        # This should be "analytics-hive.eqiad.wmnet", but doing that gives us cert errors
        host="an-coord1001.eqiad.wmnet",
        port=8281,
        http_scheme="https",
        user=USER_NAME,
        auth=PRESTO_AUTH,
        source=f"{USER_NAME}, wmfdata-python"
    )

    cursor = connection.cursor()
    final_result = None
    for command in commands:
        cursor.execute(command)
        result = cursor.fetchall()
        description = cursor.description

        # Weirdly, this happens after running a command that doesn't produce results (like a
        # CREATE TABLE or INSERT). Most users can't run those, though.
        # TO-DO: report this as a bug upstream
        if result == [[True]] and description[0][0] == "results":
            pass
        else:
            # Based on
            # https://github.com/prestodb/presto-python-client/issues/56#issuecomment-367432438
            colnames = [col[0] for col in description]
            dtypes = [col[1] for col in description]
            def setup_transform(col, desired_dtype):
                # Only Hive dates/times need special handling
                if desired_dtype in ("timestamp", "date"):
                    return lambda df: pd.to_datetime(df[col])
                else:
                    return lambda df: df[col]

            transformations = {
                col: setup_transform(col, dtype)
                for col, dtype in zip(colnames, dtypes)
            }
            
            final_result = (
                pd.DataFrame(result, columns=colnames)
                .assign(**transformations)
            )
 
    cursor.cancel()
    connection.close()

    return final_result

