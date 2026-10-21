import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor
from esphome.const import ENTITY_CATEGORY_DIAGNOSTIC, STATE_CLASS_MEASUREMENT

from . import CM1Bridge, CONF_CM1_BRIDGE_ID

CONF_CONNECTION_COUNT = "connection_count"

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_CM1_BRIDGE_ID): cv.use_id(CM1Bridge),
        cv.Optional(CONF_CONNECTION_COUNT): sensor.sensor_schema(
            accuracy_decimals=0,
            state_class=STATE_CLASS_MEASUREMENT,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
            icon="mdi:lan-connect",
        ),
    }
)


async def to_code(config):
    parent = await cg.get_variable(config[CONF_CM1_BRIDGE_ID])
    if CONF_CONNECTION_COUNT in config:
        sens = await sensor.new_sensor(config[CONF_CONNECTION_COUNT])
        cg.add(parent.set_connection_count_sensor(sens))
