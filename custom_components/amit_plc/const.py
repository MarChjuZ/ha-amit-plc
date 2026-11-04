"""Constants for the AMiT PLC integration."""

DOMAIN = "amit_plc"
SIGNAL = "amit_plc_update"
PLATFORMS = ["binary_sensor", "sensor", "switch"]

CONF_PATH = "path"
CONF_INTERVAL_MS = "interval_ms"
CONF_VARIABLES = "variables"
CONF_KIND = "kind"
CONF_NAME = "name"
CONF_VARIABLE = "variable"
CONF_UNIT = "unit"
CONF_DEVICE_CLASS = "device_class"
CONF_PRECISION = "precision"
CONF_MODEL = "model"
CONF_CONTROLLER_NAME = "name"

KIND_BINARY_SENSOR = "binary_sensor"
KIND_SENSOR = "sensor"
KIND_SWITCH = "switch"

DEFAULT_PORT = 80
DEFAULT_PATH = "/"
DEFAULT_INTERVAL_MS = 100
