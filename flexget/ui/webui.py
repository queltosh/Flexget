"""
Fires events:

webui.start
  When webui is being started, this is just before WSGI server is started. Everything else is already initialized.

webui.stop
  When webui is being shut down, the WSGI server has exited the "serve forever" loop.
"""

from __future__ import unicode_literals, division, absolute_import
import logging
import os
import urllib
import socket
import sys
from sqlalchemy.orm import scoped_session

from flask import Flask, redirect, url_for, abort, request, send_from_directory

from flexget.event import fire_event
from flexget.plugin import DependencyError
from flexget.ui import plugins as ui_plugins_pkg
from flexget.webserver import app

log = logging.getLogger('webui')

_home = None
_menu = []

manager = None
config = {}
db_session = None

def _update_menu(root):
    """Iterates trough menu navigation and sets the item selected based on the :root:"""
    for item in _menu:
        if item['href'].startswith(root):
            item['current'] = True
            log.debug('current menu item %s' % root)
        else:
            if 'current' in item:
                item.pop('current')

@app.route('/userstatic/<path:filename>')
def userstatic(filename):
    return send_from_directory(os.path.join(manager.config_base, 'userstatic'), filename)


@app.context_processor
def flexget_variables():
    path = urllib.splitquery(request.path)[0]
    root = '/' + path.split('/', 2)[1]
    # log.debug('root is: %s' % root)
    _update_menu(root)
    return {'menu': _menu, 'manager': manager}


def _strip_trailing_sep(path):
    return path.rstrip("\\/")


def _get_standard_ui_plugins_path():
    """
    :returns: List of directories where ui plugins should be tried to load from.
    """

    # Get basic path from environment
    paths = []

    env_path = os.environ.get('FLEXGET_UI_PLUGIN_PATH')
    if env_path:
        paths = [path for path in env_path.split(os.pathsep) if os.path.isdir(path)]

    # Add flexget.ui.plugins directory (core ui plugins)
    import flexget.ui.plugins
    paths.append(flexget.ui.plugins.__path__[0])
    return paths


def _load_ui_plugins_from_dirs(dirs):

    # Ensure plugins can be loaded via flexget.ui.plugins
    ui_plugins_pkg.__path__ = map(_strip_trailing_sep, dirs)

    plugins = set()
    for d in dirs:
        for f in os.listdir(d):
            path = os.path.join(d, f, '__init__.py')
            if os.path.isfile(path):
                plugins.add(f)

    for plugin in plugins:
        name = plugin.split(".")[-1]
        try:
            log.info('Loading UI plugin %s' % name)
            exec "import flexget.ui.plugins.%s" % plugin
        except DependencyError as e:
            # plugin depends on another plugin that was not imported successfully
            log.error(e.message)
        except EnvironmentError as e:
            log.info('Plugin %s: %s' % (name, str(e)))
        except Exception as e:
            log.critical('Exception while loading plugin %s' % name)
            log.exception(e)
            raise


def load_ui_plugins():

    # Add flexget.plugins directory (core plugins)
    ui_plugin_dirs = _get_standard_ui_plugins_path()

    user_plugin_dir = os.path.join(manager.config_base, 'ui_plugins')
    if os.path.isdir(user_plugin_dir):
        ui_plugin_dirs.append(user_plugin_dir)

    _load_ui_plugins_from_dirs(ui_plugin_dirs)


def register_plugin(blueprint, menu=None, order=128, home=False):
    """
    Registers UI plugin.

    :plugin: :class:`flask.Blueprint` object for this plugin.
    """
    # Set up some defaults if the plugin did not already specify them
    if blueprint.url_prefix is None:
        blueprint.url_prefix = '/' + blueprint.name
    if not blueprint.template_folder and os.path.isdir(os.path.join(blueprint.root_path, 'templates')):
        blueprint.template_folder = 'templates'
    if not blueprint.static_folder and os.path.isdir(os.path.join(blueprint.root_path, 'static')):
        blueprint.static_folder = 'static'
    log.info('Registering UI plugin %s' % blueprint.name)
    app.register_blueprint(blueprint)
    if menu:
        register_menu(blueprint.url_prefix, menu, order=order)
    if home:
        register_home(blueprint.name + '.index')


def register_menu(href, caption, order=128):
    global _menu
    _menu.append({'href': href, 'caption': caption, 'order': order})
    _menu = sorted(_menu, key=lambda item: item['order'])


def register_home(route, order=128):
    """Registers homepage elements"""
    global _home
    # TODO: currently supports only one plugin
    if _home is not None:
        raise Exception('Home is already registered')
    _home = route