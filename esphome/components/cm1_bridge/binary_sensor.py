import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import binary_sensor
from esphome.const import DEVICE_CLASS_CONNECTIVITY

from . import CM1Bridge, CONF_CM1_BRIDGE_ID

CONF_CONNECTED = "connected"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_CM1_BRIDGE_ID): cv.use_id(CM1Bridge),
        cv.Optional(CONF_CONNECTED): binary_sensor.binary_sensor_schema(device_class=DEVICE_CLASS_CONNECTIVITY),
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_CM1_BRIDGE_ID])
    if CONF_CONNECTED in config:
        sens = await binary_sensor.new_binary_sensor(config[CONF_CONNECTED])
        cg.add(parent.set_connected_sensor(sens))
