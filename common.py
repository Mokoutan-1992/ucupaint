import bpy, os, sys
from mathutils import *
from bpy.app.handlers import persistent
#from .__init__ import bl_info

TEXGROUP_PREFIX = '~TL Tex '
ADDON_NAME = 'yTexLayers'

blend_type_items = (("MIX", "Mix", ""),
	             ("ADD", "Add", ""),
	             ("SUBTRACT", "Subtract", ""),
	             ("MULTIPLY", "Multiply", ""),
	             ("SCREEN", "Screen", ""),
	             ("OVERLAY", "Overlay", ""),
	             ("DIFFERENCE", "Difference", ""),
	             ("DIVIDE", "Divide", ""),
	             ("DARKEN", "Darken", ""),
	             ("LIGHTEN", "Lighten", ""),
	             ("HUE", "Hue", ""),
	             ("SATURATION", "Saturation", ""),
	             ("VALUE", "Value", ""),
	             ("COLOR", "Color", ""),
	             ("SOFT_LIGHT", "Soft Light", ""),
	             ("LINEAR_LIGHT", "Linear Light", ""))

normal_map_type_items = (
        ('BUMP_MAP', 'Bump Map', '', 'MATCAP_09', 0),
        ('FINE_BUMP_MAP', 'Fine Bump Map', '', 'MATCAP_09', 1),
        ('NORMAL_MAP', 'Normal Map', '', 'MATCAP_23', 2)
        )

normal_blend_items = (
        ('MIX', 'Mix', ''),
        ('OVERLAY', 'Overlay', '')
        )

texture_type_items = (
        ('IMAGE', 'Image', ''),
        #('ENVIRONMENT', 'Environment', ''),
        ('BRICK', 'Brick', ''),
        ('CHECKER', 'Checker', ''),
        ('GRADIENT', 'Gradient', ''),
        ('MAGIC', 'Magic', ''),
        ('NOISE', 'Noise', ''),
        #('POINT_DENSITY', 'Point Density', ''),
        #('SKY', 'Sky', ''),
        ('VORONOI', 'Voronoi', ''),
        ('WAVE', 'Wave', ''),
        )

texcoord_type_items = (
        ('Generated', 'Generated', ''),
        ('Normal', 'Normal', ''),
        ('UV', 'UV', ''),
        ('Object', 'Object', ''),
        ('Camera', 'Camera', ''),
        ('Window', 'Window', ''),
        ('Reflection', 'Reflection', ''),
        )

channel_socket_input_bl_idnames = {
    'RGB': 'NodeSocketColor',
    'VALUE': 'NodeSocketFloatFactor',
    'NORMAL': 'NodeSocketVector',
}

channel_socket_output_bl_idnames = {
    'RGB': 'NodeSocketColor',
    'VALUE': 'NodeSocketFloat',
    'NORMAL': 'NodeSocketVector',
}

possible_object_types = {
        'MESH',
        'META',
        'CURVE',
        'SURFACE',
        'FONT'
        }

GAMMA = 2.2

def get_current_version_str():
    bl_info = sys.modules[ADDON_NAME].bl_info
    return str(bl_info['version']).replace(', ', '.').replace('(','').replace(')','')

def get_active_material():
    scene = bpy.context.scene
    engine = scene.render.engine
    if not hasattr(bpy.context, 'object'): return None
    obj = bpy.context.object

    if not obj: return None

    mat = obj.active_material

    if engine in {'BLENDER_RENDER', 'BLENDER_GAME'}:
        return None

    return mat

def in_active_layer(obj):
    scene = bpy.context.scene
    space = bpy.context.space_data
    if space.type == 'VIEW_3D' and space.local_view:
        return any([layer for layer in obj.layers_local_view if layer])
    else:
        return any([layer for i, layer in enumerate(obj.layers) if layer and scene.layers[i]])

def get_addon_filepath():

    sep = os.sep

    # Search for addon dirs
    roots = bpy.utils.script_paths()

    possible_dir_names = [ADDON_NAME, ADDON_NAME + '-master']

    for root in roots:
        if os.path.basename(root) != 'scripts': continue
        filepath = root + sep + 'addons'

        dirs = next(os.walk(filepath))[1]
        folders = [x for x in dirs if x in possible_dir_names]

        if folders:
            return filepath + sep + folders[0] + sep

    return 'ERROR: No path found for yPanel!'

def srgb_to_linear_per_element(e):
    if e <= 0.03928:
        return e/12.92
    else: 
        return pow((e + 0.055) / 1.055, 2.4)

def linear_to_srgb_per_element(e):
    if e > 0.0031308:
        return 1.055 * (pow(e, (1.0 / 2.4))) - 0.055
    else: 
        return 12.92 * e

def srgb_to_linear(inp):

    if type(inp) == float:
        return srgb_to_linear_per_element(inp)

    elif type(inp) == Color:

        c = inp.copy()

        for i in range(3):
            c[i] = srgb_to_linear_per_element(c[i])

        return c

def linear_to_srgb(inp):

    if type(inp) == float:
        return linear_to_srgb_per_element(inp)

    elif type(inp) == Color:

        c = inp.copy()

        for i in range(3):
            c[i] = linear_to_srgb_per_element(c[i])

        return c

def copy_node_props_(source, dest, extras = []):
    print()
    props = dir(source)
    filters = ['rna_type']
    filters.extend(extras)
    for prop in props:
        if prop.startswith('__'): continue
        if prop.startswith('bl_'): continue
        if prop in filters: continue
        val = getattr(source, prop)
        if 'bpy_func' in str(type(val)): continue
        # Copy stuff here
        try: 
            setattr(dest, prop, val)
            print('SUCCESS:', prop, val)
        except: 
            print('FAILED:', prop, val)

def copy_node_props(source ,dest, extras = []):
    # Copy node props
    copy_node_props_(source, dest, extras)

    if source.type == 'CURVE_RGB':
        
        # Copy mapping props
        copy_node_props_(source.mapping, dest.mapping)
        
        # Copy curve props
        for i, curve in enumerate(source.mapping.curves):
            curve_copy = dest.mapping.curves[i]
            copy_node_props_(curve, curve_copy)
    
            # Copy point props
            for j, point in enumerate(curve.points):
                if j >= len(curve_copy.points):
                    point_copy = curve_copy.points.new(point.location[0], point.location[1])
                else: point_copy = curve_copy.points[j]
                copy_node_props_(point, point_copy)
                
            # Copy selection
            for j, point in enumerate(curve.points):
                point_copy = curve_copy.points[j]
                point_copy.select = point.select
                
        # Update curve
        dest.mapping.update()
    
    elif source.type == 'VALTORGB':
    
        # Copy color ramp props
        copy_node_props_(source.color_ramp, dest.color_ramp)
        
        # Copy color ramp elements
        for i, elem in enumerate(source.color_ramp.elements):
            if i >= len(dest.color_ramp.elements):
                elem_copy = dest.color_ramp.elements.new(elem.position)
            else: elem_copy = dest.color_ramp.elements[i]
            copy_node_props_(elem, elem_copy)

    # Copy inputs default value
    for i, inp in enumerate(source.inputs):
        dest.inputs[i].default_value = inp.default_value

    # Copy outputs default value
    for i, outp in enumerate(source.outputs):
        dest.outputs[i].default_value = outp.default_value 

# Check if name already available on the list
def get_unique_name(name, items):
    unique_name = name
    name_found = [item for item in items if item.name == name]
    if name_found:
        i = 1
        while True:
            new_name = name + ' ' + str(i)
            name_found = [item for item in items if item.name == new_name]
            if not name_found:
                unique_name = new_name
                break
            i += 1

    return unique_name

def get_active_node():
    mat = get_active_material()
    if not mat or not mat.node_tree: return None
    node = mat.node_tree.nodes.active
    return node

# Specific methods for this addon
def get_active_texture_layers_node():
    #node = get_active_node()
    #if not node or node.type != 'GROUP' or not node.node_tree or not node.node_tree.tl.is_tl_node:
    #    return None
    #return node

    mat = get_active_material()
    if not mat or not mat.node_tree: return None

    nodes = mat.node_tree.nodes

    return nodes.get(mat.tl.active_tl_node)

# Some image_ops need this
#def get_active_image():
#    node = get_active_texture_layers_node()
#    if not node: return None
#    tl = node.node_tree.tl
#    nodes = node.node_tree.nodes
#    if len(tl.textures) == 0: return None
#    tex = tl.textures[tl.active_texture_index]
#    if tex.type != 'ShaderNodeTexImage': return None
#    source = nodes.get(tex.source)
#    return source.image

