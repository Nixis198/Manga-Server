import os
import importlib
import inspect
import logging
import ast
from .base import MetadataPlugin

logger = logging.getLogger(__name__)

# Calculate the absolute path to the plugins directory
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

def load_plugins():
    plugins = {}
    
    # Ensure __init__.py exists
    if not os.path.exists(os.path.join(PLUGIN_DIR, "__init__.py")):
        with open(os.path.join(PLUGIN_DIR, "__init__.py"), 'w') as f: pass

    for filename in os.listdir(PLUGIN_DIR):
        if filename.endswith(".py") and filename not in ["base.py", "manager.py", "__init__.py"]:
            module_name = f"app.plugins.{filename[:-3]}"
            try:
                # Reload if already loaded (allows hot-swapping)
                if module_name in importlib.sys.modules: # type: ignore
                    module = importlib.reload(importlib.sys.modules[module_name]) # type: ignore
                else:
                    module = importlib.import_module(module_name)
                
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, MetadataPlugin) and obj is not MetadataPlugin:
                        instance = obj()
                        plugins[instance.id] = obj
            except Exception as e:
                logger.error(f"Failed to load plugin {filename}: {e}")
                        
    return plugins

def get_plugin_instance(plugin_id: str):
    plugins = load_plugins()
    if plugin_id in plugins:
        return plugins[plugin_id]() 
    return None

def get_plugin_info_from_file(filepath: str):
    """
    Safely inspects a file using AST to find the Plugin ID and Version 
    without executing the code.
    Returns: (id, version) or None
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
            
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                # Check inheritance
                inherits = any(
                    (isinstance(b, ast.Name) and b.id == "MetadataPlugin") 
                    for b in node.bases
                )
                
                if inherits:
                    p_id = None
                    p_version = 1.0
                    
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    if target.id == "id" and isinstance(item.value, ast.Constant):
                                        p_id = item.value.value
                                    elif target.id == "version" and isinstance(item.value, ast.Constant):
                                        p_version = item.value.value
                                        
                    if p_id:
                        return (p_id, p_version)
    except Exception as e:
        logger.error(f"Error inspecting file {filepath}: {e}")
        
    return None

def get_file_path_for_plugin_id(target_id: str):
    """Finds the filename for a specific plugin ID."""
    for filename in os.listdir(PLUGIN_DIR):
        if filename.endswith(".py") and filename not in ["base.py", "manager.py", "__init__.py"]:
            path = os.path.join(PLUGIN_DIR, filename)
            info = get_plugin_info_from_file(path)
            if info and info[0] == target_id:
                return path
    return None