"""
homeassistant.components.scene
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Allows users to set and activate scenes.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/scene/
"""
import logging
from collections import namedtuple

from homeassistant.components.scene import Scene
from homeassistant.const import (
    ATTR_ENTITY_ID, STATE_OFF, STATE_ON)
from homeassistant.core import State
from homeassistant.helpers.state import reproduce_state

DEPENDENCIES = ['group']
STATE = 'scening'

CONF_ENTITIES = "entities"

SceneConfig = namedtuple('SceneConfig', ['name', 'states'])


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Sets up home assistant scene entries. """
    scene_config = config.get("config")

    add_devices([HomeAssistantScene(hass, _process_config(scene_config))])

    return True


def _process_config(scene_config):
    """ Process passed in config into a format to work with. """
    name = scene_config.get('name')

    states = {}
    c_entities = dict(scene_config.get(CONF_ENTITIES, {}))

    for entity_id in c_entities:
        if isinstance(c_entities[entity_id], dict):
            entity_attrs = c_entities[entity_id].copy()
            state = entity_attrs.pop('state', None)
            attributes = entity_attrs
        else:
            state = c_entities[entity_id]
            attributes = {}

        # YAML translates 'on' to a boolean
        # http://yaml.org/type/bool.html
        if isinstance(state, bool):
            state = STATE_ON if state else STATE_OFF
        else:
            state = str(state)

        states[entity_id.lower()] = State(entity_id, state, attributes)

    return SceneConfig(name, states)


class HomeAssistantScene(Scene):
    """ A scene is a group of entities and the states we want them to be. """

    def __init__(self, hass, scene_config):
        self.hass = hass
        self.scene_config = scene_config

    @property
    def name(self):
        return self.scene_config.name

    @property
    def device_state_attributes(self):
        """ Scene state attributes. """
        return {
            ATTR_ENTITY_ID: list(self.scene_config.states.keys()),
        }

    def activate(self):
        """ Activates scene. Tries to get entities into requested state. """
        reproduce_state(self.hass, self.scene_config.states.values(), True)
