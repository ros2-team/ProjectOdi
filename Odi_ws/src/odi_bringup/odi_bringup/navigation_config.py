"""Merge ODI controller settings into the installed Humble Nav2 configuration."""
from copy import deepcopy


def merge_navigation_config(base, overrides):
    if not isinstance(base, dict) or not isinstance(overrides, dict):
        raise ValueError('Nav2 configuration must be a mapping')
    controller = base.get('controller_server', {}).get('ros__parameters', {})
    if controller.get('FollowPath', {}).get('plugin') != 'dwb_core::DWBLocalPlanner':
        raise ValueError('ODI navigation profile requires the Humble DWB base configuration')
    result = deepcopy(base)

    def merge(target, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    # Changing the plugin must not retain incompatible DWB critic parameters.
    replacement = overrides.get('controller_server', {}).get('ros__parameters', {}).get('FollowPath', {})
    if replacement.get('plugin') and replacement['plugin'] != controller['FollowPath']['plugin']:
        result['controller_server']['ros__parameters']['FollowPath'] = {}
    merge(result, overrides)
    return result
