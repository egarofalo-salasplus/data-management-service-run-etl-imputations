
# Azure Function - ETL para Imputaciones y Fichajes

Este proyecto contiene una Azure Function diseñada para realizar el proceso ETL (Extracción, Transformación y Carga) de los datos de imputaciones y fichajes provenientes de la aplicación **Sesame HR** hacia la base de datos de personas. Este flujo de trabajo es parte de un sistema más amplio que gestiona los datos de Recursos Humanos en la organización.

## Estructura del Proyecto

```plaintext
run_etl_imputations
├── function_app.py                 # Archivo principal para configurar la aplicación
├── host.json                       # Configuración de host para Azure Functions
├── local.settings.json             # Configuración local para variables de entorno
├── requirements.txt                # Dependencias de Python
└── README.md                       # Documentación del proyecto
```

## Descripción de las Funciones

### `function_app`

Esta función extrae los datos de imputaciones desde **Sesame HR** a través de su API, realiza la transformación necesaria para estructurar los datos de acuerdo con la base de datos de personas y finalmente los carga en la base de datos. Esta operación se ejecuta periódicamente para mantener actualizados los registros de tiempo de imputación en el sistema de gestión de datos de la organización. Para fichajes sigue un proceso similar, extrayendo datos de fichajes desde **Sesame HR**, transformándolos y cargándolos en la base de datos de personas. Esto garantiza que la información de horas trabajadas esté actualizada para facilitar la generación de informes y el análisis de productividad.


## Dependencias

Las dependencias de Python están listadas en el archivo `requirements.txt`. Para instalar las dependencias, ejecuta:

```bash
pip install -r requirements.txt
```

## Ejecución Local

Para ejecutar la función de forma local, utiliza las herramientas de Azure Functions Core Tools:

```bash
func start
```

Asegúrate de haber configurado correctamente `local.settings.json` para que las variables de entorno sean accesibles durante la ejecución.

## Implementación

Para implementar esta Azure Function en Azure, asegúrate de tener configurado un grupo de recursos y una cuenta de almacenamiento en Azure. Puedes implementar directamente utilizando la CLI de Azure:

```bash
az functionapp deployment source config-zip     --resource-group <nombre-grupo-recursos>     --name <nombre-funcion>     --src <ruta-al-archivo-zip>
```

## Uso

Una vez implementada, esta función se ejecutará de acuerdo con el cronograma configurado en `host.json`, extrayendo, transformando y cargando los datos de imputaciones y fichajes de **Sesame HR** en la base de datos de personas.

## Autor

Creado por **Félix Enzo Garofalo Lanzuisi**

## Licencia

Este proyecto está bajo la Licencia MIT. Para más detalles, consulta el archivo LICENSE.
