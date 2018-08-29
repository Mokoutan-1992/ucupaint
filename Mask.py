import bpy, re, time
from bpy.props import *
from . import lib
from .common import *
from .node_connections import *
from .node_arrangements import *

def set_mask_channel_bump_nodes(c):
    tl = c.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]\.channels\[(\d+)\]', c.path_from_id())
    tex = tl.textures[int(match.group(1))]
    mask = tex.masks[int(match.group(2))]
    ch = tex.channels[int(match.group(3))]

    tree = get_tree(tex)

    need_reconnect = False

    enable_mask_source(tex, mask, False)
    mask_tree = get_mask_tree(mask)

    neighbor_uv = tree.nodes.get(c.neighbor_uv)
    different_uv = mask.texcoord_type == 'UV' and tex.uv_name != mask.uv_name

    if not neighbor_uv:
        neighbor_uv = new_node(tree, c, 'neighbor_uv', 'ShaderNodeGroup', 'Mask Neighbor UV')
        need_reconnect = True

    neighbor_uv.node_tree = lib.get_neighbor_uv_tree(mask.texcoord_type, different_uv)
    if mask.type == 'IMAGE':
        src = mask_tree.nodes.get(mask.source)
        neighbor_uv.inputs[1].default_value = src.image.size[0]
        neighbor_uv.inputs[2].default_value = src.image.size[1]
    else:
        neighbor_uv.inputs[1].default_value = 1000
        neighbor_uv.inputs[2].default_value = 1000

    if different_uv:
        tangent = tree.nodes.get(mask.tangent)
        bitangent = tree.nodes.get(mask.bitangent)

        if not tangent:
            tangent = new_node(tree, mask, 'tangent', 'ShaderNodeNormalMap', 'Mask Tangent')
            tangent.inputs[1].default_value = (1.0, 0.5, 0.5, 1.0)
            need_reconnect = True

        if not bitangent:
            bitangent = new_node(tree, mask, 'bitangent', 'ShaderNodeNormalMap', 'Mask Bitangent')
            bitangent.inputs[1].default_value = (0.5, 1.0, 0.5, 1.0)
            need_reconnect = True

        tangent.uv_map = mask.uv_name
        bitangent.uv_map = mask.uv_name
    else:
        remove_node(tree, mask, 'tangent')
        remove_node(tree, mask, 'bitangent')

    for d in neighbor_directions:

        src = tree.nodes.get(getattr(c, 'source_' + d))
        if not src:
            src = new_node(tree, c, 'source_' + d, 'ShaderNodeGroup', 'mask_' + d)
            src.node_tree = mask_tree
            src.hide = True
            need_reconnect = True

        mul = tree.nodes.get(getattr(c, 'multiply_' + d))
        if not mul:
            mul = new_node(tree, c, 'multiply_' + d, 'ShaderNodeMath', 'mul_' + d)
            mul.operation = 'MULTIPLY'
            mul.hide = True
            need_reconnect = True

    return need_reconnect

def set_mask_multiply_and_total_nodes(tree, c, ch):
    multiply = tree.nodes.get(c.multiply)
    if not multiply:
        multiply = new_node(tree, c, 'multiply', 'ShaderNodeMath', 'Mask Multiply')
        multiply.operation = 'MULTIPLY'

    mask_total = tree.nodes.get(ch.mask_total)
    if not mask_total:
        mask_total = new_node(tree, ch, 'mask_total', 'ShaderNodeMath', 'Total Channel Mask')
        mask_total.operation = 'MULTIPLY'

def add_new_mask(tex, name, mask_type, texcoord_type, uv_name, image = None):
    tl = tex.id_data.tl
    tl.halt_update = True

    tree = get_tree(tex)
    nodes = tree.nodes

    mask = tex.masks.add()
    mask.name = name
    mask.type = mask_type
    mask.texcoord_type = texcoord_type

    source = new_node(tree, mask, 'source', texture_node_bl_idnames[mask_type], 'Mask Source')
    if image:
        source.image = image
        source.color_space = 'NONE'

    uv_map = new_node(tree, mask, 'uv_map', 'ShaderNodeUVMap', 'Mask UV Map')
    uv_map.uv_map = uv_name
    mask.uv_name = uv_name

    final = new_node(tree, mask, 'final', 'NodeReroute', 'Mask Final')

    for i, root_ch in enumerate(tl.channels):
        ch = tex.channels[i]
        c = mask.channels.add()

        set_mask_multiply_and_total_nodes(tree, c, ch)

        if ch.enable_mask_bump:
            set_mask_bump_nodes(tex, ch, i)

        if ch.enable_mask_ramp:
            set_mask_ramp_nodes(tree, tex, ch)

    tl.halt_update = False

    return mask

def remove_mask_channel_nodes(tree, c):
    # Bump related
    remove_node(tree, c, 'neighbor_uv')
    remove_node(tree, c, 'source_n')
    remove_node(tree, c, 'source_s')
    remove_node(tree, c, 'source_e')
    remove_node(tree, c, 'source_w')
    remove_node(tree, c, 'multiply_n')
    remove_node(tree, c, 'multiply_s')
    remove_node(tree, c, 'multiply_e')
    remove_node(tree, c, 'multiply_w')

    # Multiply
    remove_node(tree, c, 'multiply')

def remove_mask_total_nodes(tree, tex, mask, ch_index, clean=False):
    ch = tex.channels[ch_index]

    # Remove mask total and mask intensity multiplier
    remove_node(tree, ch, 'mask_total')
    remove_node(tree, ch, 'mask_intensity_multiplier')

    # Then remove mask bump
    if ch.enable_mask_bump:
        remove_mask_bump_nodes(tex, ch, ch_index)

    # Remove mask_ramp
    if ch.enable_mask_ramp:
        unset_mask_ramp_nodes(tree, ch, clean)

def remove_mask_channel(tree, tex, ch_index):

    # Remove mask nodes
    for mask in tex.masks:

        # Get channels
        c = mask.channels[ch_index]
        ch = tex.channels[ch_index]

        # Remove mask channel nodes first
        remove_mask_channel_nodes(tree, c)

        # Remove remaining nodes
        remove_mask_total_nodes(tree, tex, mask, ch_index, True)

    # Remove the mask itself
    for mask in tex.masks:
        mask.channels.remove(ch_index)

def remove_mask(tex, mask):

    tree = get_tree(tex)

    # Remove mask nodes
    mask_tree = get_mask_tree(mask)
    remove_node(mask_tree, mask, 'source')
    remove_node(mask_tree, mask, 'hardness')

    remove_node(tree, mask, 'group_node')
    remove_node(tree, mask, 'uv_map')
    remove_node(tree, mask, 'final')
    remove_node(tree, mask, 'tangent')
    remove_node(tree, mask, 'bitangent')

    # Remove mask channel nodes
    for c in mask.channels:
        remove_mask_channel_nodes(tree, c)

    # Remove mask
    for i, m in enumerate(tex.masks):
        if m == mask:
            tex.masks.remove(i)
            break

    # Remove total mask if all mask already removed
    if len(tex.masks) == 0:
        for i, ch in enumerate(tex.channels):
            remove_mask_total_nodes(tree, tex, mask, i)

class YNewTextureMask(bpy.types.Operator):
    bl_idname = "node.y_new_texture_mask"
    bl_label = "New Texture Mask"
    bl_description = "New Texture Mask"
    bl_options = {'REGISTER', 'UNDO'}

    name = StringProperty(default='')

    type = EnumProperty(
            name = 'Mask Type',
            items = texture_type_items,
            default = 'IMAGE')

    width = IntProperty(name='Width', default = 1024, min=1, max=16384)
    height = IntProperty(name='Height', default = 1024, min=1, max=16384)

    color_option = EnumProperty(
            name = 'Color Option',
            description = 'Color Option',
            items = (
                ('WHITE', 'White (Full Opacity)', ''),
                ('BLACK', 'Black (Full Transparency)', ''),
                ),
            default='WHITE')

    hdr = BoolProperty(name='32 bit Float', default=False)

    texcoord_type = EnumProperty(
            name = 'Texture Coordinate Type',
            items = texcoord_type_items,
            default = 'UV')

    uv_name = StringProperty(default='')

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):

        # HACK: For some reason, checking context.texture on poll will cause problem
        # This method below is to get around that
        self.auto_cancel = False
        if not hasattr(context, 'texture'):
            self.auto_cancel = True
            return self.execute(context)

        obj = context.object
        self.texture = context.texture
        tex = context.texture

        name = tex.name
        if self.type != 'IMAGE':
            name += ' ' + [i[1] for i in texture_type_items if i[0] == self.type][0]
            items = tex.masks
        else:
            items = bpy.data.images
        name = 'Mask ' + name

        self.name = get_unique_name(name, items)

        if obj.type != 'MESH':
            self.texcoord_type = 'Generated'
        elif len(obj.data.uv_layers) > 0:
            # Use active uv layer name by default
            self.uv_name = obj.data.uv_layers.active.name

        return context.window_manager.invoke_props_dialog(self)

    def check(self, context):
        return True

    def draw(self, context):
        obj = context.object

        row = self.layout.split(percentage=0.4)
        col = row.column(align=False)
        col.label('Name:')
        if self.type == 'IMAGE':
            col.label('Width:')
            col.label('Height:')
            col.label('Color:')
            col.label('')
        col.label('Vector:')

        col = row.column(align=False)
        col.prop(self, 'name', text='')
        if self.type == 'IMAGE':
            col.prop(self, 'width', text='')
            col.prop(self, 'height', text='')
            col.prop(self, 'color_option', text='')
            col.prop(self, 'hdr')

        crow = col.row(align=True)
        crow.prop(self, 'texcoord_type', text='')
        if obj.type == 'MESH' and self.texcoord_type == 'UV':
            crow.prop_search(self, "uv_name", obj.data, "uv_layers", text='', icon='GROUP_UVS')

    def execute(self, context):
        if self.auto_cancel: return {'CANCELLED'}

        tlui = context.window_manager.tlui
        tex = self.texture

        # Check if texture with same name is already available
        if self.type == 'IMAGE':
            same_name = [i for i in bpy.data.images if i.name == self.name]
        else: same_name = [m for m in tex.masks if m.name == self.name]
        if same_name:
            if self.type == 'IMAGE':
                self.report({'ERROR'}, "Image named '" + self.name +"' is already available!")
            else: self.report({'ERROR'}, "Mask named '" + self.name +"' is already available!")
            return {'CANCELLED'}

        alpha = False
        img = None
        if self.type == 'IMAGE':
            img = bpy.data.images.new(self.name, self.width, self.height, alpha, self.hdr)
            if self.color_option == 'WHITE':
                img.generated_color = (1,1,1,1)
            elif self.color_option == 'BLACK':
                img.generated_color = (0,0,0,1)
            img.use_alpha = False
        mask = add_new_mask(tex, self.name, self.type, self.texcoord_type, self.uv_name, img)

        # Enable edit mask
        if self.type == 'IMAGE':
            mask.active_edit = True

        reconnect_tex_nodes(tex)
        rearrange_tex_nodes(tex)

        tlui.tex_ui.expand_masks = True
        tlui.need_update = True

        return {'FINISHED'}

class YRemoveTextureMask(bpy.types.Operator):
    bl_idname = "node.y_remove_texture_mask"
    bl_label = "Remove Texture Mask"
    bl_description = "Remove Texture Mask"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return hasattr(context, 'mask') and hasattr(context, 'texture')

    def execute(self, context):
        mask = context.mask
        tex = context.texture
        tree = get_tree(tex)

        remove_mask(tex, mask)

        reconnect_tex_nodes(tex)
        rearrange_tex_nodes(tex)

        # Seach for active edit mask
        found_active_edit = False
        for m in tex.masks:
            if m.active_edit:
                found_active_edit = True
                break

        # Use texture image as active image if active edit mask not found
        if not found_active_edit:
            if tex.type == 'IMAGE':
                source = get_tex_source(tex, tree)
                update_image_editor_image(context, source.image)
            else:
                update_image_editor_image(context, None)

        # Refresh viewport and image editor
        for area in bpy.context.screen.areas:
            if area.type in ['VIEW_3D', 'IMAGE_EDITOR', 'NODE_EDITOR']:
                area.tag_redraw()

        return {'FINISHED'}

def mask_bump_channel_items(self, context):
    tl = get_active_texture_layers_node().node_tree.tl
    tex = tl.textures[tl.active_texture_index]
    items = []
    idx = 0
    for i, root_ch in enumerate(tl.channels):
        ch = tex.channels[i]
        if root_ch.type == 'NORMAL' and not ch.active_mask_bump:
            if hasattr(bpy.utils, 'previews'): # Blender 2.7 only
                items.append((str(i), root_ch.name, '', 
                    lib.custom_icons[lib.channel_custom_icon_dict['NORMAL']].icon_id, idx))
            else:
                 items.append((str(i), root_ch.name, '', lib.channel_icon_dict['NORMAL'], idx))
            idx += 1

    return items

def mask_ramp_channel_items(self, context):
    tl = get_active_texture_layers_node().node_tree.tl
    tex = tl.textures[tl.active_texture_index]
    items = []
    idx = 0
    for i, root_ch in enumerate(tl.channels):
        ch = tex.channels[i]
        if root_ch.type != 'NORMAL' and not ch.active_mask_ramp:
            if hasattr(bpy.utils, 'previews'): # Blender 2.7 only
                items.append((str(i), root_ch.name, '', 
                    lib.custom_icons[lib.channel_custom_icon_dict[root_ch.type]].icon_id, idx))
            else:
                 items.append((str(i), root_ch.name, '', lib.channel_icon_dict['NORMAL'], idx))
            idx += 1

    return items

def update_mask_active_edit(self, context):
    if self.halt_update: return

    # Only image mask can be edited
    if self.active_edit and self.type != 'IMAGE':
        self.halt_update = True
        self.active_edit = False
        self.halt_update = False
        return

    tl = self.id_data.tl

    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]', self.path_from_id())
    tex_idx = int(match.group(1))
    tex = tl.textures[int(match.group(1))]
    mask_idx = int(match.group(2))

    if self.active_edit: 
        for m in tex.masks:
            if m == self: continue
            m.halt_update = True
            m.active_edit = False
            m.halt_update = False

    # Refresh
    tl.active_texture_index = tex_idx

def update_enable_texture_masks(self, context):
    tl = self.id_data.tl
    if tl.halt_update: return

    tex = self
    tree = get_tree(tex)
    for mask in tex.masks:
        for ch in mask.channels:
            mute = not ch.enable or not mask.enable or not tex.enable_masks

            multiply = tree.nodes.get(ch.multiply)
            multiply.mute = mute

            for d in neighbor_directions:
                mul = tree.nodes.get(getattr(ch, 'multiply_' + d))
                if mul: mul.mute = mute

def update_tex_mask_channel_enable(self, context):
    tl = self.id_data.tl
    if tl.halt_update: return

    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    mask = tex.masks[int(match.group(2))]
    tree = get_tree(tex)

    mute = not self.enable or not mask.enable or not tex.enable_masks

    multiply = tree.nodes.get(self.multiply)
    multiply.mute = mute

    for d in neighbor_directions:
        mul = tree.nodes.get(getattr(self, 'multiply_' + d))
        if mul: mul.mute = mute

def update_tex_mask_enable(self, context):
    tl = self.id_data.tl
    if tl.halt_update: return

    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    tree = get_tree(tex)

    for ch in self.channels:

        mute = not ch.enable or not self.enable or not tex.enable_masks

        multiply = tree.nodes.get(ch.multiply)
        multiply.mute = mute

        for d in neighbor_directions:
            mul = tree.nodes.get(getattr(ch, 'multiply_' + d))
            if mul: mul.mute = mute

    self.active_edit = self.enable and self.type == 'IMAGE'

def update_mask_texcoord_type(self, context):
    tl = self.id_data.tl
    if tl.halt_update: return

    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]

    reconnect_tex_nodes(tex)

def update_mask_uv_name(self, context):
    obj = context.object
    tl = self.id_data.tl
    if tl.halt_update: return

    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    tree = get_tree(tex)
    
    uv_map = tree.nodes.get(self.uv_map)
    uv_map.uv_map = self.uv_name

    # Update uv layer
    if self.active_edit and obj.type == 'MESH':

        if hasattr(obj.data, 'uv_textures'):
            uv_layers = obj.data.uv_textures
        else: uv_layers = obj.data.uv_layers

        for i, uv in enumerate(uv_layers):
            if uv.name == self.uv_name:
                if uv_layers.active_index != i:
                    uv_layers.active_index = i
                break

    # Update neighbor uv if mask bump is active
    for i, c in enumerate(self.channels):
        ch = tex.channels[i]
        if ch.enable_mask_bump:
            if set_mask_channel_bump_nodes(c):
                rearrange_tex_nodes(tex)
                reconnect_tex_nodes(tex)

def update_mask_hardness_enable(self, context):
    tl = self.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]

    tree = get_mask_tree(self)
    hardness = tree.nodes.get(self.hardness)

    if self.enable_hardness and not hardness:
        hardness = new_node(tree, self, 'hardness', 'ShaderNodeGroup', 'Mask Hardness')
        hardness.node_tree = lib.get_node_tree_lib(lib.MOD_INTENSITY_HARDNESS)
        hardness.inputs[1].default_value = self.hardness_value
    if not self.enable_hardness and hardness:
        remove_node(tree, self, 'hardness')

    reconnect_tex_nodes(tex)
    rearrange_tex_nodes(tex)

def update_mask_hardness_value(self, context):
    tl = self.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.masks\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]

    tree = get_mask_tree(self)

    hardness = tree.nodes.get(self.hardness)
    if hardness:
        hardness.inputs[1].default_value = self.hardness_value

def update_mask_ramp_intensity_value(self, context):
    tl = self.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    tree = get_tree(tex)

    mr_intensity = tree.nodes.get(self.mr_intensity)
    if mr_intensity: 
        flip_bump = any([c for c in tex.channels if c.mask_bump_flip and c.enable_mask_bump])

        if flip_bump:
            mr_intensity.inputs[1].default_value = self.mask_ramp_intensity_value * self.intensity_value
        else: mr_intensity.inputs[1].default_value = self.mask_ramp_intensity_value

def update_mask_ramp_blend_type(self, context):
    tl = self.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    tree = get_tree(tex)

    mr_blend = tree.nodes.get(self.mr_blend)
    mr_blend.blend_type = self.mask_ramp_blend_type

def set_mask_ramp_flip_nodes(tree, ch, rearrange=False):
    mr_alpha1 = tree.nodes.get(ch.mr_alpha1)
    mr_flip_hack = tree.nodes.get(ch.mr_flip_hack)
    mr_flip_blend = tree.nodes.get(ch.mr_flip_blend)

    #if flip_bump:
    if not mr_alpha1:
        mr_alpha1 = new_node(tree, ch, 'mr_alpha1', 'ShaderNodeMath', 'Mask Ramp Alpha 1')
        mr_alpha1.operation = 'MULTIPLY'
        rearrange = True

    if not mr_flip_hack:
        mr_flip_hack = new_node(tree, ch, 'mr_flip_hack', 'ShaderNodeMath', 'Mask Ramp Flip Hack')
        mr_flip_hack.operation = 'POWER'
        rearrange = True

    if not mr_flip_blend:
        mr_flip_blend = new_node(tree, ch, 'mr_flip_blend', 'ShaderNodeMixRGB', 'Mask Ramp Flip Blend')
        rearrange = True

    # Flip bump is better be muted if intensity is maximum
    if ch.intensity_value < 1.0:
        mr_flip_hack.inputs[1].default_value = 1
    else: mr_flip_hack.inputs[1].default_value = 20

    return rearrange

def unset_mask_ramp_flip_nodes(tree, ch):
    remove_node(tree, ch, 'mr_alpha1')
    remove_node(tree, ch, 'mr_flip_hack')
    remove_node(tree, ch, 'mr_flip_blend')

def set_mask_ramp_nodes(tree, tex, ch, rearrange=False):
    mr_ramp = tree.nodes.get(ch.mr_ramp)
    mr_inverse = tree.nodes.get(ch.mr_inverse)
    mr_alpha = tree.nodes.get(ch.mr_alpha)
    mr_intensity = tree.nodes.get(ch.mr_intensity)
    mr_blend = tree.nodes.get(ch.mr_blend)

    if not mr_ramp:
        mr_ramp = new_node(tree, ch, 'mr_ramp', 'ShaderNodeValToRGB', 'Mask Ramp')
        mr_ramp.color_ramp.elements[0].color = (1,1,1,1)
        mr_ramp.color_ramp.elements[1].color = (0.0,0.0,0.0,1)
        rearrange = True

    if not mr_inverse:
        mr_inverse = new_node(tree, ch, 'mr_inverse', 'ShaderNodeMath', 'Mask Ramp Inverse')
        mr_inverse.operation = 'SUBTRACT'
        mr_inverse.inputs[0].default_value = 1.0
        #mr_inverse.use_clamp = True
        rearrange = True

    if not mr_alpha:
        mr_alpha = new_node(tree, ch, 'mr_alpha', 'ShaderNodeMath', 'Mask Ramp Alpha')
        mr_alpha.operation = 'MULTIPLY'
        rearrange = True

    if not mr_intensity:
        mr_intensity = new_node(tree, ch, 'mr_intensity', 'ShaderNodeMath', 'Mask Ramp Intensity')
        mr_intensity.operation = 'MULTIPLY'
        mr_intensity.inputs[1].default_value = ch.mask_ramp_intensity_value
        rearrange = True

    if not mr_blend:
        mr_blend = new_node(tree, ch, 'mr_blend', 'ShaderNodeMixRGB', 'Mask Ramp Blend')
        rearrange = True

    mr_blend.blend_type = ch.mask_ramp_blend_type
    mr_blend.mute = not ch.enable
    if len(mr_blend.outputs[0].links) == 0:
        rearrange = True

    # Check for other channel using sharpen normal transition
    flip_bump = False
    for c in tex.channels:
        if c.enable_mask_bump and c.enable:
            if c.mask_bump_flip: flip_bump = True
            mr_intensity_multiplier = tree.nodes.get(ch.mr_intensity_multiplier)
            if not mr_intensity_multiplier:
                mr_intensity_multiplier = lib.new_intensity_multiplier_node(tree, 
                        ch, 'mr_intensity_multiplier', c.mask_bump_value)
                rearrange = True
            mr_intensity_multiplier.inputs[1].default_value = c.mask_bump_second_edge_value

    # Flip bump related
    if flip_bump:
        rearrange = set_mask_ramp_flip_nodes(tree, ch, rearrange)

    return rearrange

def unset_mask_ramp_nodes(tree, ch, clean=False):
    #mute_node(tree, ch, 'mr_blend')
    remove_node(tree, ch, 'mr_inverse')
    remove_node(tree, ch, 'mr_alpha')
    remove_node(tree, ch, 'mr_intensity_multiplier')
    remove_node(tree, ch, 'mr_intensity')
    remove_node(tree, ch, 'mr_blend')

    if clean:
        remove_node(tree, ch, 'mr_ramp')

    # Remove flip bump related nodes
    unset_mask_ramp_flip_nodes(tree, ch)

def update_enable_mask_ramp(self, context):
    T = time.time()

    tl = self.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    ch = tex.channels[int(match.group(2))]

    tree = get_tree(tex)

    if self.enable_mask_ramp:
        if set_mask_ramp_nodes(tree, tex, ch):
            rearrange_tex_nodes(tex)
            reconnect_tex_nodes(tex)
    else:
        unset_mask_ramp_nodes(tree, ch)
        reconnect_tex_nodes(tex)
        rearrange_tex_nodes(tex)

    if ch.enable_mask_ramp:
        print('INFO: Mask ramp is enabled at {:0.2f}'.format((time.time() - T) * 1000), 'ms!')
    else: print('INFO: Mask ramp is disabled at {:0.2f}'.format((time.time() - T) * 1000), 'ms!')

def get_mask_fine_bump_distance(distance):
    scale = 100
    #if mask.type == 'IMAGE':
    #    mask_tree = get_mask_tree(mask)
    #    source = mask_tree.nodes.get(mask.source)
    #    image = source.image
    #    if image: scale = image.size[0] / 10

    #return -1.0 * distance * scale
    return distance * scale

def update_mask_bump_distance(self, context):
    if not self.enable: return

    tl = self.id_data.tl
    match = re.match(r'tl\.textures\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    ch_index = int(match.group(2))
    ch = self
    tree = get_tree(tex)

    mb_fine_bump = tree.nodes.get(ch.mb_fine_bump)
    if mb_fine_bump:
        if ch.mask_bump_flip:
            mb_fine_bump.inputs[0].default_value = -get_mask_fine_bump_distance(ch.mask_bump_distance)
        else: mb_fine_bump.inputs[0].default_value = get_mask_fine_bump_distance(ch.mask_bump_distance)

def update_mask_bump_value(self, context):
    if not self.enable: return

    tl = self.id_data.tl
    m = re.match(r'tl\.textures\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(m.group(1))]
    tree = get_tree(tex)
    ch = self

    mask_intensity_multiplier = tree.nodes.get(ch.mask_intensity_multiplier)
    mb_intensity_multiplier = tree.nodes.get(ch.mb_intensity_multiplier)

    if ch.mask_bump_flip:
        mask_intensity_multiplier.inputs[1].default_value = ch.mask_bump_second_edge_value
        mb_intensity_multiplier.inputs[1].default_value = ch.mask_bump_value
    else:
        mask_intensity_multiplier.inputs[1].default_value = ch.mask_bump_value
        mb_intensity_multiplier.inputs[1].default_value = ch.mask_bump_second_edge_value

    for c in tex.channels:
        if c == ch: continue

        mr_intensity_multiplier = tree.nodes.get(c.mr_intensity_multiplier)
        if mr_intensity_multiplier:
            mr_intensity_multiplier.inputs[1].default_value = ch.mask_bump_second_edge_value

        im = tree.nodes.get(c.mask_intensity_multiplier)
        if im: im.inputs[1].default_value = ch.mask_bump_value

def check_set_mask_intensity_multiplier(tree, tex, bump_ch = None, target_ch = None):

    # No need to add mask intensity multiplier if there is no mask
    if len(tex.masks) == 0: return

    # If bump channel isn't set
    if not bump_ch:
        for c in tex.channels:
            if c.enable_mask_bump:
                bump_ch = c
                break

    # Bump channel must available
    if not bump_ch: return

    # Add intensity multiplier to other channel mask
    for i, c in enumerate(tex.channels):

        # If target channel is set, its the only one will be processed
        if target_ch and target_ch != c: continue

        # NOTE: Bump channel supposed to be already had a mask intensity multipler
        if c == bump_ch: continue

        props = ['mask_intensity_multiplier']
        if c.enable_mask_ramp: 
            props.append('mr_intensity_multiplier')

            # Fix intensity value
            mr_intensity = tree.nodes.get(c.mr_intensity)
            if mr_intensity:
                mr_intensity.inputs[1].default_value = c.mask_ramp_intensity_value * c.intensity_value

            if bump_ch.mask_bump_flip:
                set_mask_ramp_flip_nodes(tree, c)
            else:
                unset_mask_ramp_flip_nodes(tree, c)

        for prop in props:
            im = tree.nodes.get(getattr(c, prop))
            if not im:
                im = lib.new_intensity_multiplier_node(tree, c, prop, bump_ch.mask_bump_value)

            if not bump_ch.enable:
                im.mute = True
            elif prop == 'mr_intensity_multiplier':
                im.inputs[1].default_value = bump_ch.mask_bump_second_edge_value
            else:
                im.mute = False

            # Invert other mask intensity multipler if mask bump flip active
            if prop == 'mask_intensity_multiplier': #and bump_ch != c:
                if bump_ch.mask_bump_flip:
                    im.inputs['Invert'].default_value = 1.0
                else: im.inputs['Invert'].default_value = 0.0

def set_mask_bump_nodes(tex, ch, ch_index):

    tl = tex.id_data.tl

    for i, c in enumerate(tex.channels):
        if tl.channels[i].type == 'NORMAL' and c.enable_mask_bump and c != ch:
            # Disable this mask bump if other channal already use mask bump
            if c.enable:
                tl.halt_update = True
                ch.enable_mask_bump = False
                tl.halt_update = False
                return
            # Disable other mask bump if other channal aren't enabled
            else:
                tl.halt_update = True
                c.enable_mask_bump = False
                tl.halt_update = False

    tree = get_tree(tex)

    mb_fine_bump = tree.nodes.get(ch.mb_fine_bump)
    mb_inverse = tree.nodes.get(ch.mb_inverse)
    mb_blend = tree.nodes.get(ch.mb_blend)
    mb_intensity_multiplier = tree.nodes.get(ch.mb_intensity_multiplier)
    mask_intensity_multiplier = tree.nodes.get(ch.mask_intensity_multiplier)

    # Add fine bump
    if not mb_fine_bump:
        mb_fine_bump = new_node(tree, ch, 'mb_fine_bump', 'ShaderNodeGroup', 'Mask Fine Bump')
        mb_fine_bump.node_tree = lib.get_node_tree_lib(lib.FINE_BUMP)

    if ch.mask_bump_flip:
        mb_fine_bump.inputs[0].default_value = -get_mask_fine_bump_distance(ch.mask_bump_distance)
    else: mb_fine_bump.inputs[0].default_value = get_mask_fine_bump_distance(ch.mask_bump_distance)

    # Add inverse
    if not mb_inverse:
        mb_inverse = new_node(tree, ch, 'mb_inverse', 'ShaderNodeMath', 'Mask Bump Inverse')
        mb_inverse.operation = 'SUBTRACT'
        mb_inverse.inputs[0].default_value = 1.0

    if not mb_intensity_multiplier:
        mb_intensity_multiplier = lib.new_intensity_multiplier_node(tree, ch, 
                'mb_intensity_multiplier', ch.mask_bump_value)

    if not mask_intensity_multiplier:
        mask_intensity_multiplier = lib.new_intensity_multiplier_node(tree, ch, 
                'mask_intensity_multiplier', ch.mask_bump_value)

    if not ch.enable:
        mb_intensity_multiplier.mute = True
        mask_intensity_multiplier.mute = True
    else:
        mb_intensity_multiplier.mute = False
        mask_intensity_multiplier.mute = False

    if ch.mask_bump_flip:
        mask_intensity_multiplier.inputs[1].default_value = ch.mask_bump_second_edge_value
        mb_intensity_multiplier.inputs[1].default_value = ch.mask_bump_value
    else:
        mask_intensity_multiplier.inputs[1].default_value = ch.mask_bump_value
        mb_intensity_multiplier.inputs[1].default_value = ch.mask_bump_second_edge_value

    # Add intensity multiplier to other channel mask
    check_set_mask_intensity_multiplier(tree, tex, bump_ch=ch)

    # Add vector mix
    if not mb_blend:
        mb_blend = new_node(tree, ch, 'mb_blend', 'ShaderNodeGroup', 'Mask Vector Blend')
        mb_blend.node_tree = lib.get_node_tree_lib(lib.VECTOR_MIX)

    # Add per mask channel bump related nodes
    for mask in tex.masks:
        c = mask.channels[ch_index]
        set_mask_channel_bump_nodes(c)

def remove_mask_bump_nodes(tex, ch, ch_index):
    tree = get_tree(tex)

    remove_node(tree, ch, 'mb_fine_bump')
    remove_node(tree, ch, 'mb_inverse')
    remove_node(tree, ch, 'mb_intensity_multiplier')
    remove_node(tree, ch, 'mb_blend')

    for mask in tex.masks:
        disable_mask_source(tex, mask)

        #print(len(tex.masks), mask, ch_index, len(mask.channels))

        c = mask.channels[ch_index]

        remove_node(tree, mask, 'tangent')
        remove_node(tree, mask, 'bitangent')
        remove_node(tree, c, 'neighbor_uv')

        for d in neighbor_directions:
            remove_node(tree, c, 'source_' + d)
        #for d in directions_me:
            remove_node(tree, c, 'multiply_' + d)

    # Delete intensity multiplier from ramp
    for c in tex.channels:
        #mute_node(tree, c, 'mr_intensity_multiplier')
        remove_node(tree, c, 'mr_intensity_multiplier')
        remove_node(tree, c, 'mask_intensity_multiplier')

        # Ramp intensity value should only use its own value if bump aren't available
        if c.enable_mask_ramp:
            mr_intensity = tree.nodes.get(c.mr_intensity)
            if mr_intensity:
                mr_intensity.inputs[1].default_value = c.mask_ramp_intensity_value

            # Remove flip bump related nodes
            unset_mask_ramp_flip_nodes(tree, c)

def update_enable_mask_bump(self, context):
    T = time.time()

    tl = self.id_data.tl
    if tl.halt_update or not self.enable: return
    match = re.match(r'tl\.textures\[(\d+)\]\.channels\[(\d+)\]', self.path_from_id())
    tex = tl.textures[int(match.group(1))]
    ch_index = int(match.group(2))
    ch = self

    if ch.enable_mask_bump:
        set_mask_bump_nodes(tex, ch, ch_index)
    else: remove_mask_bump_nodes(tex, ch, ch_index)

    reconnect_tex_nodes(tex)
    rearrange_tex_nodes(tex)
        
    if ch.enable_mask_bump:
        print('INFO: Mask bump is enabled at {:0.2f}'.format((time.time() - T) * 1000), 'ms!')
    else: print('INFO: Mask bump is disabled at {:0.2f}'.format((time.time() - T) * 1000), 'ms!')

def enable_mask_source(tex, mask, reconnect = True):

    # Check if source tree is already available
    if mask.group_node != '': return

    tex_tree = get_tree(tex)

    # Get current source for reference
    source_ref = tex_tree.nodes.get(mask.source)
    hardness_ref = tex_tree.nodes.get(mask.hardness)

    # Create mask tree
    mask_tree = bpy.data.node_groups.new(MASKGROUP_PREFIX + mask.name, 'ShaderNodeTree')

    # Create input and outputs
    mask_tree.inputs.new('NodeSocketVector', 'Vector')
    #mask_tree.outputs.new('NodeSocketColor', 'Color')
    mask_tree.outputs.new('NodeSocketFloat', 'Value')

    start = mask_tree.nodes.new('NodeGroupInput')
    start.name = MASK_TREE_START
    end = mask_tree.nodes.new('NodeGroupOutput')
    end.name = MASK_TREE_END

    # Copy nodes from reference
    source = new_node(mask_tree, mask, 'source', source_ref.bl_idname)
    copy_node_props(source_ref, source)

    hardness = None
    if hardness_ref:
        hardness = new_node(mask_tree, mask, 'hardness', hardness_ref.bl_idname)
        copy_node_props(hardness_ref, hardness)

    # Create source node group
    group_node = new_node(tex_tree, mask, 'group_node', 'ShaderNodeGroup')
    group_node.node_tree = mask_tree

    # Remove previous nodes
    tex_tree.nodes.remove(source_ref)
    if hardness_ref:
        tex_tree.nodes.remove(hardness_ref)

    if reconnect:
        # Reconnect outside nodes
        reconnect_tex_nodes(tex)

        # Rearrange nodes
        rearrange_tex_nodes(tex)

def disable_mask_source(tex, mask, reconnect=False):

    # Check if source tree is already gone
    if mask.group_node == '': return

    tex_tree = get_tree(tex)
    mask_tree = get_mask_tree(mask)

    source_ref = mask_tree.nodes.get(mask.source)
    hardness_ref = mask_tree.nodes.get(mask.hardness)
    group_node = tex_tree.nodes.get(mask.group_node)

    # Create new nodes
    source = new_node(tex_tree, mask, 'source', source_ref.bl_idname)
    copy_node_props(source_ref, source)

    if hardness_ref:
        hardness = new_node(tex_tree, mask, 'hardness', hardness_ref.bl_idname)
        copy_node_props(hardness_ref, hardness)

    # Remove previous source
    remove_node(tex_tree, mask, 'group_node')
    bpy.data.node_groups.remove(mask_tree)

    if reconnect:
        # Reconnect outside nodes
        reconnect_tex_nodes(tex)

        # Rearrange nodes
        rearrange_tex_nodes(tex)

class YTextureMaskChannel(bpy.types.PropertyGroup):
    enable = BoolProperty(default=True, update=update_tex_mask_channel_enable)

    # Multiply between mask channels
    multiply = StringProperty(default='')

    # Bump related
    source_n = StringProperty(default='')
    source_s = StringProperty(default='')
    source_e = StringProperty(default='')
    source_w = StringProperty(default='')
    multiply_n = StringProperty(default='')
    multiply_s = StringProperty(default='')
    multiply_e = StringProperty(default='')
    multiply_w = StringProperty(default='')
    neighbor_uv = StringProperty(default='')

    # UI related
    expand_content = BoolProperty(default=False)

class YTextureMask(bpy.types.PropertyGroup):

    halt_update = BoolProperty(default=False)
    
    group_node = StringProperty(default='')

    enable = BoolProperty(
            name='Enable Mask', 
            description = 'Enable mask',
            default=True, update=update_tex_mask_enable)

    enable_hardness = BoolProperty(
            name='Enable Hardness', 
            description = 'Enable Hardness',
            default=False, update=update_mask_hardness_enable)

    hardness_value = FloatProperty(default=1.0, min=1.0, update=update_mask_hardness_value)

    active_edit = BoolProperty(
            name='Active mask for editing', 
            description='Active mask for editing', 
            default=False,
            update=update_mask_active_edit)

    type = EnumProperty(
            name = 'Mask Type',
            items = texture_type_items,
            default = 'IMAGE')

    texcoord_type = EnumProperty(
        name = 'Texture Coordinate Type',
        items = texcoord_type_items,
        default = 'UV',
        update=update_mask_texcoord_type)

    uv_name = StringProperty(default='', update=update_mask_uv_name)

    channels = CollectionProperty(type=YTextureMaskChannel)

    # Nodes
    source = StringProperty(default='')
    final = StringProperty('')

    #texcoord = StringProperty(default='')
    uv_map = StringProperty(default='')

    tangent = StringProperty(default='')
    bitangent = StringProperty(default='')

    hardness = StringProperty(default='')

    # UI related
    expand_content = BoolProperty(default=False)
    expand_channels = BoolProperty(default=False)
    expand_source = BoolProperty(default=False)
    expand_vector = BoolProperty(default=False)

def register():
    bpy.utils.register_class(YNewTextureMask)
    bpy.utils.register_class(YRemoveTextureMask)
    bpy.utils.register_class(YTextureMaskChannel)
    bpy.utils.register_class(YTextureMask)

def unregister():
    bpy.utils.unregister_class(YNewTextureMask)
    bpy.utils.unregister_class(YRemoveTextureMask)
    bpy.utils.unregister_class(YTextureMaskChannel)
    bpy.utils.unregister_class(YTextureMask)
