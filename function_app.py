import azure.functions as func
import logging
from datetime import datetime
import requests
import pandas as pd
from sqlalchemy import create_engine, inspect
import warnings
from io import StringIO
from decouple import config
import time
import os

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Secret keys para las diversas empresas
secret_key = config("SALAS_API_KEY", default=os.getenv("SALAS_API_KEY"))
server = config("DB_SERVER", default=os.getenv("DB_SERVER"))
database = config("DB_NAME", default=os.getenv("DB_NAME"))
username = config("DB_USER", default=os.getenv("DB_USER"))
password = config("DB_PASSWORD", default=os.getenv("DB_PASSWORD"))


@app.route(route="run_etl_imputations")
def run_etl_imputations(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request for ETL imputations.')
    # Obtener los parámetros from_date y to_date del cuerpo de la solicitud
    try:
        req_body = req.get_json()
        from_date = req_body.get('from_date')
        to_date = req_body.get('to_date')
        if not from_date or not to_date:
            return func.HttpResponse(
                "Tanto 'from_date' como 'to_date' deben proveerse en el request body.",
                status_code=400
            )
        # Validar formato de las fechas
        try:
            datetime.strptime(from_date, "%Y-%m-%d")
            datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            return func.HttpResponse(
                "'from_date' y 'to_date' deben estar en formato YYYY-MM-DD.",
                status_code=400
            )

    except ValueError:
        return func.HttpResponse(
            "Invalid request body. JSON expected.",
            status_code=400
        )

    # Código ETL adaptado
    start_time = time.perf_counter()

    # Definir las funciones adicionales y lógica de negocio
    def get_api_integration_csv(endpoint, params=None):
        url = "https://api-integration-ms.azurewebsites.net"
        headers = {
            "Authorization": f"Bearer {secret_key}"
        }
        url_csv = f"{url}{endpoint}"
        response = requests.get(url_csv,
                                headers=headers,
                                params=params,
                                timeout=5000)
        if response.status_code == 200:
            csv_text = response.text
            data = StringIO(csv_text)
            df = pd.read_csv(data)
            return df
        else:
            logging.error(f"Error en la solicitud: {response.status_code}")
            return None

    # ### Datos de empleados desde SESAME
    employees_endpoint = "/sesame/employees-csv"
    employees_dataframes = []
    status = ["active", "inactive"]
    for stat in status:
        params = {
            "status": stat
        }
        df = get_api_integration_csv(employees_endpoint, params)
        employees_dataframes.append(df)

    df_employees = pd.concat(employees_dataframes, ignore_index=True)
    logging.info("Datos de empleados cargados.")

    # ### Datos de horas teóricas desde SESAME
    worked_hours_endpoint = "/sesame/worked-hours-csv"

    # Generar un rango de fechas
    date_range = pd.date_range(start=from_date, end=to_date)

    # Inicializar una lista para almacenar los DataFrames
    dataframes = []

    # Iterar sobre cada día en el rango de fechas
    for i, single_date in enumerate(date_range):
        # Formatear la fecha al formato requerido por el endpoint
        day_str = single_date.strftime("%Y-%m-%d")
        logging.info(f"Carga de datos horas teóricas - Progreso {(i + 1)/date_range.shape[0]*100:.2f}% - {day_str}")

        # Definir los parámetros para la solicitud de API
        params = {
            "from_date": day_str,
            "to_date": day_str
        }

        # Llamar al endpoint y obtener el DataFrame para esa fecha
        if i % 20 == 0:
            time.sleep(30)
        df_daily = get_api_integration_csv(worked_hours_endpoint, params)
        df_daily["date"] = day_str

        # Agregar el DataFrame a la lista si no está vacío
        if not df_daily.empty:
            dataframes.append(df_daily)

    # Concatenar todos los DataFrames en uno solo
    df_worked_hours = pd.concat(dataframes, ignore_index=True)
    logging.info("Datos de horas trabajadas cargados.")

    # ### Datos de fichajes desde SESAME
    work_entries_endpoint = "/sesame/work-entries-csv"
    params = {
        "from_date": from_date,
        "to_date": to_date
    }

    df_work_entries = get_api_integration_csv(work_entries_endpoint, params)
    logging.info("Datos de fichajes cargados.")

    # ### Datos de imputaciones desde SESAME
    time_entries_endpoint = "/sesame/time-entries-csv"
    params = {
        "from_date": from_date,
        "to_date": to_date
    }
    df_time_entries = get_api_integration_csv(time_entries_endpoint, params)
    logging.info("Datos de imputaciones cargados.")

    # ### Datos de Asignaciones de Departamento
    department_assignations_endpoint = "/sesame/employee-department-assignations-csv"
    df_department_assignations = get_api_integration_csv(department_assignations_endpoint)
    logging.info("Datos de asignaciones de departamento cargados.")

    # ## Preparación de tablas de imputaciones
    logging.info("Inicia el procesamiento de los datos para tabla de imputaciones.")
    # Crear DataFrame para registros de imputaciones
    df_imputations = pd.DataFrame()

    # ### Convertir de String a Fecha
    df_imputations["fecha"] = pd.to_datetime(df_time_entries["time_entry_in_datetime"]).dt.date

    # ### Tarea
    df_imputations["tarea"] = df_time_entries["comment"]

    # ### ID de empleado (GUID de Sesame)
    df_imputations["employee_id"] = df_time_entries["employee_id"]

    # ### Cliente
    df_imputations = pd.merge(df_imputations, df_employees[["id", "company_name"]], left_on="employee_id", right_on="id")
    df_imputations["cliente"] = df_imputations["company_name"]
    df_imputations = df_imputations.drop(["id", "company_name"], axis=1)

    # ### Proyecto
    df_imputations["proyecto"] = df_time_entries["project"]

    # ### Etiqueta
    df_imputations["etiqueta"] = df_time_entries["tags"]

    # ### Precio Hora
    df_imputations = pd.merge(df_imputations, df_employees[["id", "price_per_hour"]], left_on="employee_id", right_on="id")
    df_imputations["precio_hora"] = df_imputations["price_per_hour"]
    df_imputations = df_imputations.drop(["id", "price_per_hour"], axis=1)

    # ### Horas imputadas
    df_imputations["time_entry_in_datetime"] = pd.to_datetime(df_time_entries["time_entry_in_datetime"])
    df_imputations["time_entry_out_datetime"] = pd.to_datetime(df_time_entries["time_entry_out_datetime"])
    df_imputations["horas_imputadas"] = (df_imputations["time_entry_out_datetime"] - df_imputations["time_entry_in_datetime"]).dt.total_seconds() / 3600
    df_imputations = df_imputations.drop(["time_entry_in_datetime", "time_entry_out_datetime"], axis=1)

    # ### Conexión con Base de datos
    # Crear la conexión utilizando SQLAlchemy y pyodbc
    connection_string = f'mssql+pyodbc://{username}:{password}@{server}/{database}?driver=ODBC+Driver+17+for+SQL+Server'
    engine = create_engine(connection_string)
    logging.info("Conexión con base de datos SQL.")

    # #### Cargar la tabla Dim_Empleado
    # Consulta SQL para obtener todos los registros de la tabla 'Dim_Empleado'
    query = "SELECT * FROM dbo.Dim_Empleado"

    # Leer los datos en un DataFrame de pandas
    with engine.connect() as connection:
        df_employees_db = pd.read_sql(query, connection)

    # Filtramos para quedarnos solo con el ID y el DNI
    df_employee_id = df_employees_db[["empleado_id", "DNI"]]
    df_employee_id = df_employees_db.groupby(["DNI"]).agg({
        "empleado_id": "last"
    }).reset_index()

    # #### Cargar la tabla de empresas
    # Consulta SQL para obtener todos los registros de la tabla 'Dim_Empresa'
    query = "SELECT * FROM dbo.Dim_Empresa"

    # Leer los datos en un DataFrame de pandas
    with engine.connect() as connection:
        df_company = pd.read_sql(query, connection)

    # Filtramos para quedarnos solo con el ID y el nombre
    df_company_id = df_company[["empresa_id", "nombre"]]

    # #### Cargar tabla Dim_Departamento
    # Consulta SQL para obtener todos los registros de la tabla 'Dim_Empresa'
    query = "SELECT * FROM dbo.Dim_Departamento"

    # Leer los datos en un DataFrame de pandas
    with engine.connect() as connection:
        df_department = pd.read_sql(query, connection)

    # ### Cotejar imputaciones con id de empleado
    df_imputations = pd.merge(df_imputations, df_employees[["id", "nid"]], left_on="employee_id", right_on="id", how="left")
    df_imputations = df_imputations.drop(["id"], axis=1)

    df_imputations = pd.merge(df_imputations, df_employee_id, left_on="nid", right_on="DNI")
    df_imputations = df_imputations.drop(["DNI"], axis=1)

    # ### Cotejar imputaciones con id de empresa
    # Función para determinar si el nombre de la empresa está en la tabla de dimension de la BD
    # y si esta existe devolver su id
    def get_field_id(field_name, serie, comparation_field, id_field):
        """
        Verifica si alguna de las cadenas en la lista de referencias está contenida en el texto.

        Parameters
        ----------
        field_name : str
            Cadena de texto donde se realizará la búsqueda.
        serie : pandas.Series
            Serie de cadenas a buscar en el texto.
        comparation_field : str
            Nombre de la columna con el valor a buscar
        id_field : str
            Nombre de la columna con el id a devolver

        Returns
        -------
        int
            id del campo a buscar, si no existe devuelve None
        """
        for _, row in serie.iterrows():
            if row[comparation_field].lower() in field_name.lower():
                return row[id_field]
        return None

    df_imputations["empresa_id"] = df_imputations["cliente"].apply(lambda x: get_field_id(x, df_company_id, "nombre", "empresa_id"))

    # ### Cotejar imputaciones con id de departamento
    df_department_assignations["created_at"] = pd.to_datetime(df_department_assignations["created_at"])
    df_department_assignations["updated_at"] = pd.to_datetime(df_department_assignations["updated_at"])
    index_of_last_update = df_department_assignations.groupby(["employee_id"])["updated_at"].idxmax()
    df_department_last_update = df_department_assignations.loc[index_of_last_update]

    df_imputations = pd.merge(df_imputations, df_department_last_update[["employee_id", "department_name"]], how="left", on="employee_id")

    df_imputations["departamento_id"] = df_imputations["department_name"].apply(lambda x: get_field_id(x, df_department, "nombre", "departamento_id")).astype(int)

    # ### Eliminar columnas innecesarias en imputaciones
    df_imputations = df_imputations[["fecha", "tarea", "cliente", "proyecto", "etiqueta", "precio_hora", "horas_imputadas", "empresa_id", "departamento_id", "empleado_id"]]

    # ### Tratar valores nulos
    df_imputations = df_imputations.fillna({"tarea": "", "etiqueta": "No especificada"})

    # ### Resumir datos por empleado, fecha y tarea
    df_imputations_summary = df_imputations.groupby(["empleado_id", "fecha", "tarea"]).agg({
        "cliente": "first",
        "proyecto": "first",
        "etiqueta": "first",
        "precio_hora": "first",
        "horas_imputadas": "sum",
        "empresa_id": "first",
        "departamento_id": "first"
    }).reset_index()

    df_imputations_summary = df_imputations_summary[["fecha", "tarea", "cliente", "proyecto", "etiqueta", "precio_hora", "horas_imputadas", "empresa_id", "departamento_id", "empleado_id"]]

    # ## Actualizar tabla de Imputaciones en Base de Datos
    # Nombre de la tabla en la base de datos
    schema = "dbo"
    table_name = "Fact_Imputaciones"
    table_complete_name = schema + "." + table_name
    table_df = df_imputations_summary.copy()

    with engine.connect() as connection:
        # Crear la tabla si no existe
        if not inspect(engine).has_table(table_name, schema=schema):
            # Insertar los datos en la tabla SQL sin modificar la estructura de la tabla
            table_df.to_sql(table_name, con=connection, schema=schema, if_exists='append', index=False)
            logging.info("Datos introducidos con éxito.")
        else:
            logging.info(f"La tabla {table_name} ya existe.")
            # Leer la tabla existente
            df_table_existing = pd.read_sql(f'SELECT * FROM {table_complete_name}', connection)
            
            # Identificar registros que son nuevos
            df_table_new = table_df[~table_df.set_index(["empleado_id", "fecha", "tarea"]).index.isin(df_table_existing.set_index(["empleado_id", "fecha", "tarea"]).index)]
            
            # Insertar los registros nuevos
            if not df_table_new.empty:
                df_table_new.to_sql(table_name, con=engine, schema=schema, index=False, if_exists='append')
                logging.info("Datos actualizados con éxito.")
            else:
                logging.info(f"La tabla {table_name} está actualizada. No se agregó ningún registro")


    # ## Preparación de tabla Fichajes
    logging.info("Inicia el procesamiento de los datos para tabla de Fichajes.")
    
    # ### Copiar tabla de fichajes
    df_singing = df_worked_hours.groupby(["employeeId", "date"]).agg({
        "secondsWorked": "sum",
        "secondsToWork": "sum",
        "secondsBalance": "sum"
    }).reset_index()

    # ### Cotejar fichajes con id de empleado
    df_singing = pd.merge(df_singing, df_employees[["id", "nid", "company_name"]], left_on="employeeId", right_on="id", how="left")
    df_singing = df_singing.drop(["id"], axis=1)

    df_singing = pd.merge(df_singing, df_employee_id, left_on="nid", right_on="DNI", how="left")

    # ### Cotejar fichajes con id de empresa
    df_singing["empresa_id"] = df_singing["company_name"].apply(lambda x: get_field_id(x, df_company_id, "nombre", "empresa_id"))

    # ### Cotejar fichajes con id de departamento
    df_singing = pd.merge(df_singing, df_department_last_update[["employee_id", "department_name"]], how="left", left_on= "employeeId", right_on="employee_id")
    df_singing["department_name"] = df_singing["department_name"]

    df_singing["department_name"] = df_singing["department_name"].fillna("No asignado")

    df_singing = df_singing.drop(["employee_id", "DNI"], axis=1)

    df_singing["departamento_id"] = df_singing["department_name"].apply(lambda x: get_field_id(x, df_department, "nombre", "departamento_id"))

    # ### Eliminar columnas innecesarias en fichajes
    df_singing = df_singing[["date", "secondsToWork", "secondsWorked", "empresa_id", "departamento_id", "empleado_id"]]

    # ### Renombrar columnas en fichajes
    df_singing = df_singing.rename(columns={
        "date": "fecha",
        "secondsToWork": "tiempo_teorico",
        "secondsWorked": "tiempo_trabajado"
    })

    # ### Cambiar tipo a columnas de fichaje
    # Reemplazar los valores '-' por 0.0 en la columna 'horas_trabajadas'
    df_singing['tiempo_teorico'] = df_singing['tiempo_teorico'].astype(float)
    df_singing['tiempo_trabajado'] = df_singing['tiempo_trabajado'].astype(float)

    # ### Inicializar o actualizar tabla Fact_Fichajes
    # Nombre de la tabla en la base de datos
    schema = "dbo"
    table_name = "Fact_Fichajes"
    table_complete_name = schema + "." + table_name
    table_df = df_singing.copy()

    with engine.connect() as connection:
        # Crear la tabla si no existe
        if not inspect(engine).has_table(table_name, schema=schema):
            # Insertar los datos en la tabla SQL sin modificar la estructura de la tabla
            table_df.to_sql(table_name, con=connection, schema=schema, if_exists='append', index=False)
            logging.info("Datos introducidos con éxito.")
        else:
            logging.info(f"La tabla {table_name} ya existe.")
            # Leer la tabla existente
            df_table_existing = pd.read_sql(f'SELECT * FROM {table_complete_name}', connection)
            
            # Identificar registros que son nuevos
            df_table_new = table_df[~table_df.set_index(['fecha', 'empleado_id']).index.isin(df_table_existing.set_index(['fecha', 'empleado_id']).index)]
            
            # Insertar los registros nuevos
            if not df_table_new.empty:
                df_table_new.to_sql(table_name, con=engine, schema=schema, index=False, if_exists='append')
                logging.info("Datos actualizados con éxito.")
            else:
                logging.info(f"La tabla {table_name} está actualizada. No se agregó ningún registro")

    end_time = time.perf_counter()

    # Calcular el tiempo transcurrido
    elapsed_time = end_time - start_time
    minutes = int(elapsed_time // 60)
    seconds = elapsed_time % 60
    
    logging.info(f"Tiempo de ejecución de pipeline: {minutes} minutos y {seconds:.0f} segundos.")

    return func.HttpResponse(
        f"ETL ejecutado con éxito. Tiempo de ejecución: {minutes} minutos y {seconds:.0f} segundos.",
        status_code=200
    )
