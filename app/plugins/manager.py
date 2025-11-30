import os
import importlib
import inspect
import logging
from .base import MetadataPlugin

# Setup logger to catch import errors
logger = logging.getLogger(__name__)

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

def load_plugins():
    plugins = {}
    
    # Ensure the directory is treated as a package
    if not os.path.exists(os.path.join(PLUGIN_DIR, "__init__.py")):
        with open(os.path.join(PLUGIN_DIR, "__init__.py"), 'w') as f:
            pass

    for filename in os.listdir(PLUGIN_DIR):
        if filename.endswith(".py") and filename not in ["base.py", "manager.py", "__init__.py"]:
            
            # Construct module path (e.g., "app.plugins.test_plugin")
            module_name = f"app.plugins.{filename[:-3]}"
            
            try:
                # Reload if already loaded (allows updating plugins without restart)
                if module_name in importlib.sys.modules: # type: ignore
                    module = importlib.reload(importlib.sys.modules[module_name]) # type: ignore
                else:
                    module = importlib.import_module(module_name)
                
                # Find classes
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, MetadataPlugin) and obj is not MetadataPlugin:
                        instance = obj()
                        plugins[instance.id] = obj
                        
            except Exception as e:
                logger.error(f"Failed to load plugin {filename}: {e}")
                print(f"Error loading {filename}: {e}")
                        
    return plugins

def get_plugin_instance(plugin_id: str):
    plugins = load_plugins()
    if plugin_id in plugins:
        return plugins[plugin_id]() 
    return None