import bpy, re, time
from bpy.props import *
from mathutils import *
from .common import *
from .bake_common import *
from .subtree import *
from .node_connections import *
from .node_arrangements import *
from . import lib, Layer, Mask, ImageAtlas, Modifier, MaskModifier

def transfer_uv(obj, mat, entity, uv_map):

    uv_layers = get_uv_layers(obj)
    uv_layers.active = uv_layers.get(uv_map)

    # Check entity
    m1 = re.match(r'^yp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^yp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if m1: 
        source = get_layer_source(entity)
        mapping = get_layer_mapping(entity)
    elif m2: 
        source = get_mask_source(entity)
        mapping = get_mask_mapping(entity)
    else: return

    image = source.image
    if not image: return

    # Get image settings
    segment = None
    use_alpha = False
    if image.yia.is_image_atlas and entity.segment_name != '':
        segment = image.yia.segments.get(entity.segment_name)
        width = segment.width
        height = segment.height
        if image.yia.color == 'WHITE':
            col = (1.0, 1.0, 1.0, 1.0)
        elif image.yia.color == 'BLACK':
            col = (0.0, 0.0, 0.0, 1.0)
        else: 
            col = (0.0, 0.0, 0.0, 0.0)
            use_alpha = True
    else:
        width = image.size[0]
        height = image.size[1]
        # Change color if baked image is found
        if 'Pointiness' in image.name:
            col = (0.73, 0.73, 0.73, 1.0)
        elif 'AO' in image.name:
            col = (1.0, 1.0, 1.0, 1.0)
        else:
            col = (0.0, 0.0, 0.0, 0.0)
            use_alpha = True

    # Create temp image as bake target
    temp_image = bpy.data.images.new(name='__TEMP',
            width=width, height=height, alpha=True, float_buffer=image.is_float)
    temp_image.colorspace_settings.name = 'Linear'
    temp_image.generated_color = col

    # Create bake nodes
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    emit = mat.node_tree.nodes.new('ShaderNodeEmission')

    # Set image to temp nodes
    src = mat.node_tree.nodes.new('ShaderNodeTexImage')
    src.image = image
    src_uv = mat.node_tree.nodes.new('ShaderNodeUVMap')
    src_uv.uv_map = entity.uv_name

    # Copy mapping
    mapp = mat.node_tree.nodes.new('ShaderNodeMapping')

    mapp.translation[0] = mapping.translation[0]
    mapp.translation[1] = mapping.translation[1]
    mapp.translation[2] = mapping.translation[2]

    mapp.rotation[0] = mapping.rotation[0]
    mapp.rotation[1] = mapping.rotation[1]
    mapp.rotation[2] = mapping.rotation[2]

    mapp.scale[0] = mapping.scale[0]
    mapp.scale[1] = mapping.scale[1]
    mapp.scale[2] = mapping.scale[2]

    # Get material output
    output = get_active_mat_output_node(mat.node_tree)
    ori_bsdf = output.inputs[0].links[0].from_socket

    straight_over = None
    if use_alpha:
        straight_over = mat.node_tree.nodes.new('ShaderNodeGroup')
        straight_over.node_tree = get_node_tree_lib(lib.STRAIGHT_OVER)
        straight_over.inputs[1].default_value = 0.0

    # Set temp image node
    tex.image = temp_image
    mat.node_tree.nodes.active = tex

    # Links
    mat.node_tree.links.new(src_uv.outputs[0], mapp.inputs[0])
    mat.node_tree.links.new(mapp.outputs[0], src.inputs[0])
    rgb = src.outputs[0]
    alpha = src.outputs[1]
    if straight_over:
        mat.node_tree.links.new(rgb, straight_over.inputs[2])
        mat.node_tree.links.new(alpha, straight_over.inputs[3])
        rgb = straight_over.outputs[0]

    mat.node_tree.links.new(rgb, emit.inputs[0])
    mat.node_tree.links.new(emit.outputs[0], output.inputs[0])

    # Bake!
    bpy.ops.object.bake()

    # Copy results to original image
    target_pxs = list(image.pixels)
    temp_pxs = list(temp_image.pixels)

    if segment:
        start_x = width * segment.tile_x
        start_y = height * segment.tile_y
    else:
        start_x = 0
        start_y = 0

    for y in range(height):
        temp_offset_y = width * 4 * y
        offset_y = image.size[0] * 4 * (y + start_y)
        for x in range(width):
            temp_offset_x = 4 * x
            offset_x = 4 * (x + start_x)
            for i in range(3):
                target_pxs[offset_y + offset_x + i] = temp_pxs[temp_offset_y + temp_offset_x + i]

    # Bake alpha if using alpha
    #srgb2lin = None
    if use_alpha:
        #srgb2lin = mat.node_tree.nodes.new('ShaderNodeGroup')
        #srgb2lin.node_tree = get_node_tree_lib(lib.SRGB_2_LINEAR)

        #mat.node_tree.links.new(src.outputs[1], srgb2lin.inputs[0])
        #mat.node_tree.links.new(srgb2lin.outputs[0], emit.inputs[0])
        mat.node_tree.links.new(src.outputs[1], emit.inputs[0])

        # Bake again!
        bpy.ops.object.bake()

        temp_pxs = list(temp_image.pixels)

        for y in range(height):
            temp_offset_y = width * 4 * y
            offset_y = image.size[0] * 4 * (y + start_y)
            for x in range(width):
                temp_offset_x = 4 * x
                offset_x = 4 * (x + start_x)
                target_pxs[offset_y + offset_x + 3] = temp_pxs[temp_offset_y + temp_offset_x]

    # Copy back edited pixels to original image
    image.pixels = target_pxs

    # Remove temp nodes
    simple_remove_node(mat.node_tree, tex)
    simple_remove_node(mat.node_tree, emit)
    simple_remove_node(mat.node_tree, src)
    simple_remove_node(mat.node_tree, src_uv)
    simple_remove_node(mat.node_tree, mapp)
    if straight_over:
        simple_remove_node(mat.node_tree, straight_over)
    #if srgb2lin:
    #    simple_remove_node(mat.node_tree, srgb2lin)

    mat.node_tree.links.new(ori_bsdf, output.inputs[0])

    # Update entity transform
    entity.translation = (0.0, 0.0, 0.0)
    entity.rotation = (0.0, 0.0, 0.0)
    entity.scale = (1.0, 1.0, 1.0)

    # Change uv of entity
    entity.uv_name = uv_map

class YTransferSomeLayerUV(bpy.types.Operator):
    bl_idname = "node.y_transfer_some_layer_uv"
    bl_label = "Transfer Some Layer UV"
    bl_description = "Transfer some layers/masks UV by baking it to other uv (this will take quite some time to finish)."
    bl_options = {'REGISTER', 'UNDO'}

    from_uv_map = StringProperty(default='')
    uv_map = StringProperty(default='')
    uv_map_coll = CollectionProperty(type=bpy.types.PropertyGroup)

    samples = IntProperty(name='Bake Samples', 
            description='Bake Samples, more means less jagged on generated textures', 
            default=1, min=1)

    margin = IntProperty(name='Bake Margin',
            description = 'Bake margin in pixels',
            default=5, subtype='PIXEL')

    @classmethod
    def poll(cls, context):
        return get_active_ypaint_node() and context.object.type == 'MESH' # and hasattr(context, 'layer')

    def invoke(self, context, event):
        obj = self.obj = context.object
        scene = self.scene = context.scene

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # UV Map collections update
        self.uv_map_coll.clear()
        for uv in uv_layers:
            if not uv.name.startswith(TEMP_UV):
                self.uv_map_coll.add().name = uv.name

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):

        if is_28():
            row = self.layout.split(factor=0.4)
        else: row = self.layout.split(percentage=0.4)

        col = row.column(align=False)
        col.label(text='From UV:')
        col.label(text='To UV:')
        col.label(text='Samples:')
        col.label(text='Margin:')

        col = row.column(align=False)
        col.prop_search(self, "from_uv_map", self, "uv_map_coll", text='', icon='GROUP_UVS')
        col.prop_search(self, "uv_map", self, "uv_map_coll", text='', icon='GROUP_UVS')
        col.prop(self, 'samples', text='')
        col.prop(self, 'margin', text='')

    def execute(self, context):

        T = time.time()

        if self.from_uv_map == '' or self.uv_map == '':
            self.report({'ERROR'}, "From or To UV Map cannot be empty!")
            return {'CANCELLED'}

        if self.from_uv_map == self.uv_map:
            self.report({'ERROR'}, "From and To UV cannot have same value!")
            return {'CANCELLED'}

        mat = get_active_material()
        node = get_active_ypaint_node()
        yp = node.node_tree.yp

        # Prepare bake settings
        remember_before_bake(self, context, yp)
        prepare_bake_settings(self, context, yp)

        for layer in yp.layers:
            #print(layer.name)
            if layer.type == 'IMAGE' and layer.uv_name == self.from_uv_map:
                transfer_uv(self.obj, mat, layer, self.uv_map)

            for mask in layer.masks:
                if mask.type == 'IMAGE' and mask.uv_name == self.from_uv_map:
                    transfer_uv(self.obj, mat, mask, self.uv_map)

        #return {'FINISHED'}

        # Recover bake settings
        recover_bake_settings(self, context, yp)

        # Refresh mapping and stuff
        yp.active_layer_index = yp.active_layer_index

        print('INFO: All layer and masks that using', self.from_uv_map, 'is transferred to', self.uv_map, 'at', '{:0.2f}'.format(time.time() - T), 'seconds!')

        return {'FINISHED'}

class YTransferLayerUV(bpy.types.Operator):
    bl_idname = "node.y_transfer_layer_uv"
    bl_label = "Transfer Layer UV"
    bl_description = "Transfer Layer UV by baking it to other uv (this will take quite some time to finish)."
    bl_options = {'REGISTER', 'UNDO'}

    uv_map = StringProperty(default='')
    uv_map_coll = CollectionProperty(type=bpy.types.PropertyGroup)

    samples = IntProperty(name='Bake Samples', 
            description='Bake Samples, more means less jagged on generated textures', 
            default=1, min=1)

    margin = IntProperty(name='Bake Margin',
            description = 'Bake margin in pixels',
            default=5, subtype='PIXEL')

    @classmethod
    def poll(cls, context):
        return get_active_ypaint_node() and context.object.type == 'MESH' # and hasattr(context, 'layer')

    def invoke(self, context, event):
        obj = self.obj = context.object
        scene = self.scene = context.scene

        if hasattr(context, 'mask'):
            self.entity = context.mask

        elif hasattr(context, 'layer'):
            self.entity = context.layer

        if not self.entity:
            return self.execute(context)

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # UV Map collections update
        self.uv_map_coll.clear()
        for uv in uv_layers:
            if not uv.name.startswith(TEMP_UV) and uv.name != self.entity.uv_name:
                self.uv_map_coll.add().name = uv.name

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        if is_28():
            row = self.layout.split(factor=0.4)
        else: row = self.layout.split(percentage=0.4)

        col = row.column(align=False)
        col.label(text='Target UV:')
        col.label(text='Samples:')
        col.label(text='Margin:')

        col = row.column(align=False)
        col.prop_search(self, "uv_map", self, "uv_map_coll", text='', icon='GROUP_UVS')
        col.prop(self, 'samples', text='')
        col.prop(self, 'margin', text='')

    def execute(self, context):
        T = time.time()

        if not hasattr(self, 'entity'):
            return {'CANCELLED'}

        if self.entity.type != 'IMAGE' or self.entity.texcoord_type != 'UV':
            self.report({'ERROR'}, "Only works with image layer/mask with UV Mapping")
            return {'CANCELLED'}

        if self.uv_map == '':
            self.report({'ERROR'}, "Target UV Map cannot be empty!")
            return {'CANCELLED'}

        if self.uv_map == self.entity.uv_name:
            self.report({'ERROR'}, "This layer/mask already use " + self.uv_map + "!")
            return {'CANCELLED'}

        mat = get_active_material()
        yp = self.entity.id_data.yp

        # Prepare bake settings
        remember_before_bake(self, context, yp)
        prepare_bake_settings(self, context, yp)

        # Transfer UV
        transfer_uv(self.obj, mat, self.entity, self.uv_map)

        # Recover bake settings
        recover_bake_settings(self, context, yp)

        # Refresh mapping and stuff
        yp.active_layer_index = yp.active_layer_index

        print('INFO:', self.entity.name, 'UV is transferred from', self.entity.uv_name, 'to', self.uv_map, 'at', '{:0.2f}'.format(time.time() - T), 'seconds!')

        return {'FINISHED'}

def resize_image(image, width, height, colorspace='Linear', samples=1, margin=0, segment=None):

    book = remember_before_bake_()

    if segment:
        ori_width = segment.width
        ori_height = segment.height
    else:
        ori_width = image.size[0]
        ori_height = image.size[1]

    if ori_width == width and ori_height == height:
        return

    if segment:
        new_segment = ImageAtlas.get_set_image_atlas_segment(
                    width, height, image.yia.color, image.is_float) #, ypup.image_atlas_size)
        scaled_img = new_segment.id_data

        ori_start_x = segment.width * segment.tile_x
        ori_start_y = segment.height * segment.tile_y

        start_x = width * new_segment.tile_x
        start_y = height * new_segment.tile_y
    else:
        scaled_img = bpy.data.images.new(name='__TEMP__', 
            width=width, height=height, alpha=True, float_buffer=image.is_float)
        scaled_img.colorspace_settings.name = colorspace
        if image.filepath != '' and not image.packed_file:
            scaled_img.filepath = image.filepath

        start_x = 0
        start_y = 0

        new_segment = None

    # Set active collection to be root collection
    if is_28():
        ori_layer_collection = bpy.context.view_layer.active_layer_collection
        bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection

    # Create new plane
    bpy.ops.object.mode_set(mode = 'OBJECT')
    bpy.ops.mesh.primitive_plane_add(calc_uvs=True)
    plane_obj = bpy.context.view_layer.objects.active

    prepare_bake_settings_(book, [plane_obj], samples=samples, margin=margin)

    # If using image atlas, transform uv
    if segment:
        uv_layers = get_uv_layers(plane_obj)

        # Transform current uv using previous segment
        #uv_layer = uv_layers.active
        for i, d in enumerate(plane_obj.data.uv_layers.active.data):
            if i == 0: # Top right
                d.uv.x = (ori_start_x + segment.width) / image.size[0]
                d.uv.y = (ori_start_y + segment.height) / image.size[1]
            elif i == 1: # Top left
                d.uv.x = ori_start_x / image.size[0]
                d.uv.y = (ori_start_y + segment.height) / image.size[1]
            elif i == 2: # Bottom left
                d.uv.x = ori_start_x / image.size[0]
                d.uv.y = ori_start_y / image.size[1]
            elif i == 3: # Bottom right
                d.uv.x = (ori_start_x + segment.width) / image.size[0]
                d.uv.y = ori_start_y / image.size[1]

        # Create new uv and transform it using new segment
        temp_uv_layer = uv_layers.new(name='__TEMP')
        uv_layers.active = temp_uv_layer
        for i, d in enumerate(plane_obj.data.uv_layers.active.data):
            if i == 0: # Top right
                d.uv.x = (start_x + width) / scaled_img.size[0]
                d.uv.y = (start_y + height) / scaled_img.size[1]
            elif i == 1: # Top left
                d.uv.x = start_x / scaled_img.size[0]
                d.uv.y = (start_y + height) / scaled_img.size[1]
            elif i == 2: # Bottom left
                d.uv.x = start_x / scaled_img.size[0]
                d.uv.y = start_y / scaled_img.size[1]
            elif i == 3: # Bottom right
                d.uv.x = (start_x + width) / scaled_img.size[0]
                d.uv.y = start_y / scaled_img.size[1]

    #return{'FINISHED'}

    mat = bpy.data.materials.new('__TEMP__')
    mat.use_nodes = True
    plane_obj.active_material = mat

    output = get_active_mat_output_node(mat.node_tree)
    emi = mat.node_tree.nodes.new('ShaderNodeEmission')
    uv_map = mat.node_tree.nodes.new('ShaderNodeUVMap')
    uv_map.uv_map = 'UVMap'
    target_tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    target_tex.image = scaled_img
    source_tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    source_tex.image = image
    straight_over = mat.node_tree.nodes.new('ShaderNodeGroup')
    straight_over.node_tree = get_node_tree_lib(lib.STRAIGHT_OVER)
    straight_over.inputs[1].default_value = 0.0

    # Connect nodes
    mat.node_tree.links.new(uv_map.outputs[0], source_tex.inputs[0])
    mat.node_tree.links.new(source_tex.outputs[0], straight_over.inputs[2])
    mat.node_tree.links.new(source_tex.outputs[1], straight_over.inputs[3])
    mat.node_tree.links.new(straight_over.outputs[0], emi.inputs[0])
    mat.node_tree.links.new(emi.outputs[0], output.inputs[0])
    mat.node_tree.nodes.active = target_tex

    # Bake
    bpy.ops.object.bake()

    # Create alpha image as bake target
    alpha_img = bpy.data.images.new(name='__TEMP_ALPHA__',
            width=width, height=height, alpha=True, float_buffer=image.is_float)
    alpha_img.colorspace_settings.name = 'Linear'

    # Retransform back uv
    if segment:
        for i, d in enumerate(plane_obj.data.uv_layers.active.data):
            if i == 0: # Top right
                d.uv.x = 1.0
                d.uv.y = 1.0
            elif i == 1: # Top left
                d.uv.x = 0.0
                d.uv.y = 1.0
            elif i == 2: # Bottom left
                d.uv.x = 0.0
                d.uv.y = 0.0
            elif i == 3: # Bottom right
                d.uv.x = 1.0
                d.uv.y = 0.0

    # Setup texture
    target_tex.image = alpha_img
    mat.node_tree.links.new(source_tex.outputs[1], emi.inputs[0])

    # Bake again!
    bpy.ops.object.bake()

    # Copy alpha image to scaled image
    target_pxs = list(scaled_img.pixels)
    temp_pxs = list(alpha_img.pixels)

    for y in range(height):
        temp_offset_y = width * 4 * y
        offset_y = scaled_img.size[0] * 4 * (y + start_y)
        for x in range(width):
            temp_offset_x = 4 * x
            offset_x = 4 * (x + start_x)
            target_pxs[offset_y + offset_x + 3] = temp_pxs[temp_offset_y + temp_offset_x]

    scaled_img.pixels = target_pxs

    # Replace original image to scaled image
    replace_image(image, scaled_img)

    # Remove temp datas
    if straight_over.node_tree.users == 1:
        bpy.data.node_groups.remove(straight_over.node_tree)
    bpy.data.images.remove(alpha_img)
    bpy.data.materials.remove(mat)
    plane = plane_obj.data
    bpy.ops.object.delete()
    bpy.data.meshes.remove(plane)

    # Recover settings
    recover_bake_settings_(book)

    # Recover original active layer collection
    if is_28():
        bpy.context.view_layer.active_layer_collection = ori_layer_collection

    return scaled_img, new_segment

class YResizeImage(bpy.types.Operator):
    bl_idname = "node.y_resize_image"
    bl_label = "Resize Image Layer/Mask"
    bl_description = "Resize image of layer or mask"
    bl_options = {'REGISTER', 'UNDO'}

    layer_name = StringProperty(default='')
    image_name = StringProperty(default='')

    width = IntProperty(name='Width', default = 1024, min=1, max=4096)
    height = IntProperty(name='Height', default = 1024, min=1, max=4096)

    samples = IntProperty(name='Bake Samples', 
            description='Bake Samples, more means less jagged on generated image', 
            default=1, min=1)

    @classmethod
    def poll(cls, context):
        #return hasattr(context, 'image') and hasattr(context, 'layer')
        return get_active_ypaint_node() and context.object.type == 'MESH'

    def invoke(self, context, event):
        #if hasattr(context, 'image') and hasattr(context, 'layer'):
        #    self.image = context.image
        #    self.layer = context.layer
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        if is_28():
            row = self.layout.split(factor=0.4)
        else: row = self.layout.split(percentage=0.4)
        col = row.column(align=True)

        col.label(text='Width:')
        col.label(text='Height:')
        col.label(text='Samples:')

        col = row.column(align=True)

        col.prop(self, 'width', text='')
        col.prop(self, 'height', text='')
        col.prop(self, 'samples', text='')

    def execute(self, context):

        #if not hasattr(self, 'image') or not hasattr(self, 'layer'):
        #    self.report({'ERROR'}, "No active image/layer found!")
        #    return {'CANCELLED'}

        #image = self.image
        #layer = self.layer
        #yp = layer.id_data.yp

        yp = get_active_ypaint_node().node_tree.yp
        layer = yp.layers.get(self.layer_name)
        image = bpy.data.images.get(self.image_name)

        if not layer or not image:
            self.report({'ERROR'}, "Image/layer is not found!")
            return {'CANCELLED'}

        # Get entity
        entity = layer
        mask_entity = False
        for mask in layer.masks:
            if mask.active_edit:
                entity = mask
                mask_entity = True
                break

        # Get original size
        segment = None
        if image.yia.is_image_atlas:
            segment = image.yia.segments.get(entity.segment_name)
            ori_width = segment.width
            ori_height = segment.height
        else:
            ori_width = image.size[0]
            ori_height = image.size[1]

        if ori_width == self.width and ori_height == self.height:
            self.report({'ERROR'}, "This image already had the same size!")
            return {'CANCELLED'}

        scaled_img, new_segment = resize_image(image, self.width, self.height, 'Linear', self.samples, 0, segment)

        if new_segment:
            entity.segment_name = new_segment.name
            segment.unused = True
            update_mapping(entity)

        # Refresh active layer
        yp.active_layer_index = yp.active_layer_index

        return {'FINISHED'}

class YBakeChannels(bpy.types.Operator):
    """Bake Channels to Image(s)"""
    bl_idname = "node.y_bake_channels"
    bl_label = "Bake channels to Image"
    bl_options = {'REGISTER', 'UNDO'}

    width = IntProperty(name='Width', default = 1024, min=1, max=4096)
    height = IntProperty(name='Height', default = 1024, min=1, max=4096)

    uv_map = StringProperty(default='')
    uv_map_coll = CollectionProperty(type=bpy.types.PropertyGroup)

    samples = IntProperty(name='Bake Samples', 
            description='Bake Samples, more means less jagged on generated textures', 
            default=1, min=1)

    margin = IntProperty(name='Bake Margin',
            description = 'Bake margin in pixels',
            default=5, subtype='PIXEL')

    #hdr = BoolProperty(name='32 bit Float', default=False)

    fxaa = BoolProperty(name='Use FXAA', 
            description = "Use FXAA to baked images (doesn't work with float images)",
            default=True)

    aa_level = IntProperty(
        name='Anti Aliasing Level',
        description='Super Sample Anti Aliasing Level (1=off)',
        default=1, min=1, max=2)

    force_bake_all_polygons = BoolProperty(
            name='Force Bake all Polygons',
            description='Force bake all polygons, useful if material is not using direct polygon (ex: solidify material)',
            default=False)

    @classmethod
    def poll(cls, context):
        return get_active_ypaint_node() and context.object.type == 'MESH'

    def invoke(self, context, event):
        node = get_active_ypaint_node()
        yp = node.node_tree.yp
        obj = self.obj = context.object
        scene = self.scene = context.scene

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # Use active uv layer name by default
        if obj.type == 'MESH' and len(uv_layers) > 0:
            if uv_layers.get(yp.baked_uv_name):
                self.uv_map = yp.baked_uv_name
            else:
                active_name = uv_layers.active.name
                if active_name == TEMP_UV:
                    self.uv_map = yp.layers[yp.active_layer_index].uv_name
                else: self.uv_map = uv_layers.active.name

            # UV Map collections update
            self.uv_map_coll.clear()
            for uv in uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

        if len(yp.channels) > 0:
            for ch in yp.channels:
                baked = node.node_tree.nodes.get(ch.baked)
                if baked and baked.image:
                    self.width = baked.image.size[0]
                    self.height = baked.image.size[1]
                    break

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        return True

    def draw(self, context):
        if is_28():
            row = self.layout.split(factor=0.4)
        else: row = self.layout.split(percentage=0.4)
        col = row.column(align=True)

        col.label(text='Width:')
        col.label(text='Height:')
        #col.label(text='')
        col.separator()
        col.label(text='Samples:')
        col.label(text='Margin:')
        col.label(text='AA Level:')
        col.separator()
        col.label(text='UV Map:')
        col.separator()
        col.label(text='')
        col.label(text='')

        col = row.column(align=True)

        col.prop(self, 'width', text='')
        col.prop(self, 'height', text='')
        #col.prop(self, 'hdr')
        col.separator()

        col.prop(self, 'samples', text='')
        col.prop(self, 'margin', text='')
        col.prop(self, 'aa_level', text='')
        col.separator()

        col.prop_search(self, "uv_map", self, "uv_map_coll", text='', icon='GROUP_UVS')
        col.separator()
        col.prop(self, 'fxaa', text='Use FXAA')
        col.prop(self, 'force_bake_all_polygons')

    def execute(self, context):

        T = time.time()

        node = get_active_ypaint_node()
        tree = node.node_tree
        yp = tree.yp
        ypui = context.window_manager.ypui
        obj = context.object
        mat = obj.active_material

        book = remember_before_bake_(yp)

        if BL28_HACK:
        #if is_28():

            if len(yp.uvs) > MAX_VERTEX_DATA - len(obj.data.vertex_colors):
                self.report({'ERROR'}, "Maximum vertex colors reached! Need at least " + str(len(uvs)) + " vertex color(s)!")
                return {'CANCELLED'}

            # Update tangent sign vertex color
            for uv in yp.uvs:
                tangent_process = tree.nodes.get(uv.tangent_process)
                if tangent_process:
                    tangent_process.inputs['Backface Always Up'].default_value = 1.0 if yp.enable_backface_always_up else 0.0
                    tangent_process.inputs['Blender 2.8 Cycles Hack'].default_value = 1.0
                    tansign = tangent_process.node_tree.nodes.get('_tangent_sign')
                    vcol = refresh_tangent_sign_vcol(obj, uv.name)
                    if vcol: tansign.attribute_name = vcol.name

        #return {'FINISHED'}

        # Disable use baked first
        if yp.use_baked:
            yp.use_baked = False

        # Get all objects using material
        objs = [obj]
        meshes = [obj.data]
        if mat.users > 1:
            for ob in get_scene_objects():
                if ob.type != 'MESH': continue
                for i, m in enumerate(ob.data.materials):
                    if m == mat:
                        ob.active_material_index = i
                        if ob not in objs and ob.data not in meshes:
                            objs.append(ob)
                            meshes.append(ob.data)

        # Multi materials setup
        ori_mat_ids = {}
        ori_loop_locs = {}
        for ob in objs:

            # Get uv map
            uv_layers = get_uv_layers(ob)
            uvl = uv_layers.get(self.uv_map)

            # Need to assign all polygon to active material if there are multiple materials
            ori_mat_ids[ob.name] = []
            ori_loop_locs[ob.name] = []

            if len(ob.data.materials) > 1:

                active_mat_id = [i for i, m in enumerate(ob.data.materials) if m == mat][0]
                for p in ob.data.polygons:

                    # Set uv location to (0,0) if not using current material
                    if uvl and not self.force_bake_all_polygons:
                        uv_locs = []
                        for li in p.loop_indices:
                            uv_locs.append(uvl.data[li].uv.copy())
                            if p.material_index != active_mat_id:
                                uvl.data[li].uv = Vector((0.0, 0.0))

                        ori_loop_locs[ob.name].append(uv_locs)

                    # Set active mat
                    ori_mat_ids[ob.name].append(p.material_index)
                    p.material_index = active_mat_id

        # AA setup
        #if self.aa_level > 1:
        margin = self.margin * self.aa_level
        width = self.width * self.aa_level
        height = self.height * self.aa_level

        # Prepare bake settings
        prepare_bake_settings_(book, objs, yp, self.samples, margin, self.uv_map, disable_problematic_modifiers=True)

        # Bake channels
        for ch in yp.channels:
            ch.no_layer_using = not is_any_layer_using_channel(ch)
            if not ch.no_layer_using:
                #if ch.type != 'NORMAL': continue
                use_hdr = not ch.use_clamp
                bake_channel(self.uv_map, mat, node, ch, width, height, use_hdr=use_hdr)
                #return {'FINISHED'}

        # AA process
        if self.aa_level > 1:
            for ch in yp.channels:

                baked = tree.nodes.get(ch.baked)
                if baked and baked.image:
                    resize_image(baked.image, self.width, self.height, 
                            baked.image.colorspace_settings.name)

                if ch.type == 'NORMAL':

                    baked_disp = tree.nodes.get(ch.baked_disp)
                    if baked_disp and baked_disp.image:
                        resize_image(baked_disp.image, self.width, self.height, 
                                baked.image.colorspace_settings.name)

                    baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
                    if baked_normal_overlay and baked_normal_overlay.image:
                        resize_image(baked_normal_overlay.image, self.width, self.height, 
                                baked.image.colorspace_settings.name)

        # FXAA
        if self.fxaa:
            for ch in yp.channels:
                # FXAA doesn't work with hdr image
                if not ch.use_clamp: continue

                baked = tree.nodes.get(ch.baked)
                if baked and baked.image:
                    fxaa_image(baked.image)
                    #return {'FINISHED'}

                if ch.type == 'NORMAL':

                    baked_disp = tree.nodes.get(ch.baked_disp)
                    if baked_disp and baked_disp.image:
                        fxaa_image(baked_disp.image)

                    baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
                    if baked_normal_overlay and baked_normal_overlay.image:
                        fxaa_image(baked_normal_overlay.image)

        # Set baked uv
        yp.baked_uv_name = self.uv_map

        # Recover bake settings
        recover_bake_settings_(book, yp)

        for ob in objs:
            # Recover material index
            if ori_mat_ids[ob.name]:
                for i, p in enumerate(ob.data.polygons):
                    if ori_mat_ids[ob.name][i] != p.material_index:
                        p.material_index = ori_mat_ids[ob.name][i]

            if ori_loop_locs[ob.name]:

                # Get uv map
                uv_layers = get_uv_layers(ob)
                uvl = uv_layers.get(self.uv_map)

                # Recover uv locations
                if uvl:
                    for i, p in enumerate(ob.data.polygons):
                        for j, li in enumerate(p.loop_indices):
                            #print(ori_loop_locs[ob.name][i][j])
                            uvl.data[li].uv = ori_loop_locs[ob.name][i][j]

        # Use bake results
        yp.halt_update = True
        yp.use_baked = True
        yp.halt_update = False

        # Check subdiv Setup
        height_ch = get_root_height_channel(yp)
        if height_ch:
            check_subdiv_setup(height_ch)

        # Update global uv
        check_uv_nodes(yp)

        # Recover hack
        #if is_28():
        if BL28_HACK:
            # Refresh tangent sign hacks
            update_enable_tangent_sign_hacks(yp, context)

        # Rearrange
        rearrange_yp_nodes(tree)
        reconnect_yp_nodes(tree)

        # Refresh active channel index
        yp.active_channel_index = yp.active_channel_index

        print('INFO:', tree.name, 'channels is baked at', '{:0.2f}'.format(time.time() - T), 'seconds!')

        return {'FINISHED'}

def merge_channel_items(self, context):
    node = get_active_ypaint_node()
    yp = node.node_tree.yp
    layer = yp.layers[yp.active_layer_index]
    #layer = self.layer
    #neighbor_layer = self.neighbor_layer

    items = []

    counter = 0
    for i, ch in enumerate(yp.channels):
        if not layer.channels[i].enable: continue
        if hasattr(lib, 'custom_icons'):
            icon_name = lib.channel_custom_icon_dict[ch.type]
            items.append((str(i), ch.name, '', lib.custom_icons[icon_name].icon_id, counter))
        else: items.append((str(i), ch.name, '', lib.channel_icon_dict[ch.type], counter))
        counter += 1

    return items

def remember_and_disable_layer_modifiers_and_transforms(layer, disable_masks=False):
    yp = layer.id_data.yp

    oris = {}

    oris['mods'] = []
    for mod in layer.modifiers:
        oris['mods'].append(mod.enable)
        mod.enable = False

    oris['ch_mods'] = {}
    oris['ch_trans_bumps'] = []
    oris['ch_trans_aos'] = []
    oris['ch_trans_ramps'] = []

    for i, c in enumerate(layer.channels):
        rch = yp.channels[i]
        ch_name = rch.name

        oris['ch_mods'][ch_name] = []
        for mod in c.modifiers:
            oris['ch_mods'][ch_name].append(mod.enable)
            mod.enable = False

        oris['ch_trans_bumps'].append(c.enable_transition_bump)
        oris['ch_trans_aos'].append(c.enable_transition_ao)
        oris['ch_trans_ramps'].append(c.enable_transition_ramp)

        if rch.type == 'NORMAL':
            if c.enable_transition_bump:
                c.enable_transition_bump = False
        else:
            if c.enable_transition_ao:
                c.enable_transition_ao = False
            if c.enable_transition_ramp:
                c.enable_transition_ramp = False

    oris['masks'] = []
    for i, m in enumerate(layer.masks):
        oris['masks'].append(m.enable)
        if m.enable and disable_masks:
            m.enable = False

    return oris

def recover_layer_modifiers_and_transforms(layer, oris):
    yp = layer.id_data.yp

    # Recover original layer modifiers
    for i, mod in enumerate(layer.modifiers):
        mod.enable = oris['mods'][i]

    for i, c in enumerate(layer.channels):
        rch = yp.channels[i]
        ch_name = rch.name

        # Recover original channel modifiers
        for j, mod in enumerate(c.modifiers):
            mod.enable = oris['ch_mods'][ch_name][j]

        # Recover original channel transition effects
        if rch.type == 'NORMAL':
            if oris['ch_trans_bumps'][i]:
                c.enable_transition_bump = oris['ch_trans_bumps'][i]
        else:
            if oris['ch_trans_aos'][i]:
                c.enable_transition_ao = oris['ch_trans_aos'][i]
            if oris['ch_trans_ramps'][i]:
                c.enable_transition_ramp = oris['ch_trans_ramps'][i]

    for i, m in enumerate(layer.masks):
        if oris['masks'][i] != m.enable:
            m.enable = oris['masks'][i]

def remove_layer_modifiers_and_transforms(layer):
    yp = layer.id_data.yp

    # Remove layer modifiers
    for i, mod in reversed(list(enumerate(layer.modifiers))):

        # Delete the nodes
        mod_tree = get_mod_tree(layer)
        Modifier.delete_modifier_nodes(mod_tree, mod)
        layer.modifiers.remove(i)

    for i, c in enumerate(layer.channels):
        rch = yp.channels[i]
        ch_name = rch.name

        # Remove channel modifiers
        for j, mod in reversed(list(enumerate(c.modifiers))):

            # Delete the nodes
            mod_tree = get_mod_tree(c)
            Modifier.delete_modifier_nodes(mod_tree, mod)
            c.modifiers.remove(j)

        # Remove channel transition effects
        if rch.type == 'NORMAL' and c.enable_transition_bump: 
            c.enable_transition_bump = False
            c.show_transition_bump = False
        else:
            if c.enable_transition_ao:
                c.enable_transition_ao = False
                c.show_transition_ao = False
            if c.enable_transition_ramp:
                c.enable_transition_ramp = False
                c.show_transition_ramp = False

    # Remove layer masks
    for i, m in enumerate(layer.masks):
        Mask.remove_mask(layer, m, bpy.context.object)

class YMergeLayer(bpy.types.Operator):
    bl_idname = "node.y_merge_layer"
    bl_label = "Merge layer"
    bl_description = "Merge Layer"
    bl_options = {'REGISTER', 'UNDO'}

    direction = EnumProperty(
            name = 'Direction',
            items = (('UP', 'Up', ''),
                     ('DOWN', 'Down', '')),
            default = 'UP')

    channel_idx = EnumProperty(
            name = 'Channel',
            description = 'Channel for merge reference',
            items = merge_channel_items)
            #update=update_channel_idx_new_layer)

    apply_modifiers = BoolProperty(
            name = 'Apply Layer Modifiers',
            description = 'Apply layer modifiers',
            default = False)

    apply_neighbor_modifiers = BoolProperty(
            name = 'Apply Neighbor Modifiers',
            description = 'Apply neighbor modifiers',
            default = True)

    #height_aware = BoolProperty(
    #        name = 'Height Aware',
    #        description = 'Height will take account for merge',
    #        default = True)

    @classmethod
    def poll(cls, context):
        group_node = get_active_ypaint_node()
        return (context.object and group_node and len(group_node.node_tree.yp.layers) > 0 
                and len(group_node.node_tree.yp.channels) > 0)

    def invoke(self, context, event):
        node = get_active_ypaint_node()
        yp = node.node_tree.yp

        # Get active layer
        layer_idx = self.layer_idx = yp.active_layer_index
        layer = self.layer = yp.layers[layer_idx]

        self.error_message = ''

        enabled_chs =  [ch for ch in layer.channels if ch.enable]
        if not any(enabled_chs):
            self.error_message = "Need at least one layer channel enabled!"

        if self.direction == 'UP':
            neighbor_idx, neighbor_layer = self.neighbor_idx, self.neighbor_layer = get_upper_neighbor(layer)
        elif self.direction == 'DOWN':
            neighbor_idx, neighbor_layer = self.neighbor_idx, self.neighbor_layer = get_lower_neighbor(layer)

        if not neighbor_layer:
            self.error_message = "No neighbor found!"

        elif not neighbor_layer.enable or not layer.enable:
            self.error_message = "Both layer should be enabled!"

        elif neighbor_layer.parent_idx != layer.parent_idx:
            self.error_message = "Cannot merge with layer with different parent!"

        elif neighbor_layer.type == 'GROUP' or layer.type == 'GROUP':
            self.error_message = "Merge doesn't works with layer group!"

        # Get height channnel
        height_root_ch = self.height_root_ch = get_root_height_channel(yp)
        height_ch_idx = self.height_ch_idx = get_channel_index(height_root_ch)

        if height_root_ch and neighbor_layer:
            height_ch = self.height_ch = layer.channels[height_ch_idx] 
            neighbor_height_ch = self.neighbor_height_ch = neighbor_layer.channels[height_ch_idx] 

            if (layer.channels[height_ch_idx].enable and 
                neighbor_layer.channels[height_ch_idx].enable):
                if height_ch.normal_map_type != neighbor_height_ch.normal_map_type:
                    self.error_message =  "These two layers has different normal map type!"
        else:
            height_ch = self.height_ch = None
            neighbor_height_ch = self.neighbor_height_ch = None

        # Get source
        self.source = get_layer_source(layer)

        if layer.type == 'IMAGE':
            if not self.source.image:
                self.error_message = "This layer has no image!"

        if self.error_message != '':
            return self.execute(context)

        # Set default value for channel index
        for i, c in enumerate(layer.channels):
            nc = neighbor_layer.channels[i]
            if c.enable and nc.enable:
                self.channel_idx = str(i)
                break

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        #col = self.layout.column()
        if is_28():
            row = self.layout.split(factor=0.5)
        else: row = self.layout.split(percentage=0.5)

        col = row.column(align=False)
        col.label(text='Main Channel:')
        col.label(text='Apply Modifiers:')
        col.label(text='Apply Neighbor Modifiers:')

        col = row.column(align=False)
        col.prop(self, 'channel_idx', text='')
        col.prop(self, 'apply_modifiers', text='')
        col.prop(self, 'apply_neighbor_modifiers', text='')

    def execute(self, context):
        T = time.time()

        wm = context.window_manager
        node = get_active_ypaint_node()
        tree = node.node_tree
        yp = tree.yp
        obj = context.object
        mat = obj.active_material
        scene = context.scene

        if self.error_message != '':
            self.report({'ERROR'}, self.error_message)
            return {'CANCELLED'}

        # Localize variables
        layer = self.layer
        layer_idx = self.layer_idx
        neighbor_layer = self.neighbor_layer
        neighbor_idx = self.neighbor_idx
        source = self.source

        # Height channel
        height_root_ch = self.height_root_ch
        height_ch = self.height_ch
        neighbor_height_ch = self.neighbor_height_ch

        # Get main reference channel
        main_ch = yp.channels[int(self.channel_idx)]
        ch = layer.channels[int(self.channel_idx)]
        neighbor_ch = neighbor_layer.channels[int(self.channel_idx)]

        # Get parent dict
        parent_dict = get_parent_dict(yp)

        # Check layer
        if (layer.type == 'IMAGE' and layer.texcoord_type == 'UV'): # and neighbor_layer.type == 'IMAGE'):

            self.scene = context.scene
            self.samples = 1
            self.margin = 5
            self.uv_map = layer.uv_name
            self.obj = obj

            remember_before_bake(self, context, yp)
            prepare_bake_settings(self, context, yp)

            #yp.halt_update = True

            # Ge list of parent ids
            #pids = get_list_of_parent_ids(layer)

            # Disable other layers
            #layer_oris = []
            #for i, l in enumerate(yp.layers):
            #    layer_oris.append(l.enable)
            #    #if i in pids:
            #    #    l.enable = True
            #    if l not in {layer, neighbor_layer}:
            #        l.enable = False

            # Get max height
            if height_root_ch and main_ch.type == 'NORMAL':
                end_max_height = tree.nodes.get(height_root_ch.end_max_height)
                ori_max_height = end_max_height.outputs[0].default_value
                max_height = get_max_height_from_list_of_layers([layer, neighbor_layer], int(self.channel_idx))
                end_max_height.outputs[0].default_value = max_height

            # Disable modfiers and transformations if apply modifiers is not enabled
            if not self.apply_modifiers:
                mod_oris = remember_and_disable_layer_modifiers_and_transforms(layer, True)

            if not self.apply_neighbor_modifiers:
                neighbor_oris = remember_and_disable_layer_modifiers_and_transforms(neighbor_layer, False)

            # Make sure to Use mix on layer channel
            if main_ch.type != 'NORMAL':
                ori_blend_type = ch.blend_type
                ch.blend_type = 'MIX'
            else:
                ori_blend_type = ch.normal_blend_type
                ch.normal_blend_type = 'MIX'

            #yp.halt_update = False

            # Enable alpha on main channel (will also update all the nodes)
            ori_enable_alpha = main_ch.enable_alpha
            main_ch.enable_alpha = True

            # Reconnect tree with merged layer ids
            reconnect_yp_nodes(tree, [layer_idx, neighbor_idx])

            # Bake main channel
            merge_success = bake_channel(layer.uv_name, mat, node, main_ch, target_layer=layer)
            #return {'FINISHED'}

            # Recover bake settings
            recover_bake_settings(self, context, yp)

            if not self.apply_modifiers:
                recover_layer_modifiers_and_transforms(layer, mod_oris)
            else: remove_layer_modifiers_and_transforms(layer)

            # Recover layer enable
            #for i, le in enumerate(layer_oris):
            #    if yp.layers[i].enable != le:
            #        yp.layers[i].enable = le

            # Recover max height
            if height_root_ch and main_ch.type == 'NORMAL':
                end_max_height.outputs[0].default_value = ori_max_height

            # Recover original props
            main_ch.enable_alpha = ori_enable_alpha
            if main_ch.type != 'NORMAL':
                ch.blend_type = ori_blend_type
            else: ch.normal_blend_type = ori_blend_type

            if merge_success:
                # Remove neighbor layer
                Layer.remove_layer(yp, neighbor_idx)

                if height_ch and main_ch.type == 'NORMAL' and height_ch.normal_map_type == 'BUMP_MAP':
                    height_ch.bump_distance = max_height

                rearrange_yp_nodes(tree)
                reconnect_yp_nodes(tree)

                # Refresh index routine
                yp.active_layer_index = min(layer_idx, neighbor_idx)
            else:
                self.report({'ERROR'}, "Merge failed for some reason!")
                return {'CANCELLED'}
            
        #elif (layer.type == 'COLOR' and neighbor_layer.type == 'COLOR' 
        #        and len(layer.masks) != 0 and len(neighbor_layer.masks) == len(layer.masks)):
        #    pass
        else:
            self.report({'ERROR'}, "This kind of merge is not supported yet (or ever)!")
            return {'CANCELLED'}

        return {'FINISHED'}

class YMergeMask(bpy.types.Operator):
    bl_idname = "node.y_merge_mask"
    bl_label = "Merge mask"
    bl_description = "Merge Mask"
    bl_options = {'REGISTER', 'UNDO'}

    direction = EnumProperty(
            name = 'Direction',
            items = (('UP', 'Up', ''),
                     ('DOWN', 'Down', '')),
            default = 'UP')

    @classmethod
    def poll(cls, context):
        return get_active_ypaint_node() and hasattr(context, 'mask') and hasattr(context, 'layer')

    def execute(self, context):
        mask = context.mask
        layer = context.layer
        yp = layer.id_data.yp
        obj = context.object
        mat = obj.active_material
        scene = context.scene
        node = get_active_ypaint_node()

        # Get number of masks
        num_masks = len(layer.masks)
        if num_masks < 2: return {'CANCELLED'}

        # Get mask index
        m = re.match(r'yp\.layers\[(\d+)\]\.masks\[(\d+)\]', mask.path_from_id())
        index = int(m.group(2))

        # Get neighbor index
        if self.direction == 'UP' and index > 0:
            neighbor_idx = index-1
        elif self.direction == 'DOWN' and index < num_masks-1:
            neighbor_idx = index+1
        else:
            return {'CANCELLED'}

        if mask.type != 'IMAGE':
            self.report({'ERROR'}, "Need image mask!")
            return {'CANCELLED'}

        # Get source
        source = get_mask_source(mask)
        if not source.image:
            self.report({'ERROR'}, "Mask image is missing!")
            return {'CANCELLED'}

        # Target image
        segment = None
        if source.image.yia.is_image_atlas and mask.segment_name != '':
            segment = source.image.yia.segments.get(mask.segment_name)
            width = segment.width
            height = segment.height

            img = bpy.data.images.new(name='__TEMP',
                    width=width, height=height, alpha=True, float_buffer=source.image.is_float)

            if source.image.yia.color == 'WHITE':
                img.generated_color = (1.0, 1.0, 1.0, 1.0)
            elif source.image.yia.color == 'BLACK':
                img.generated_color = (0.0, 0.0, 0.0, 1.0)
            else: img.generated_color = (0.0, 0.0, 0.0, 0.0)

            img.colorspace_settings.name = 'Linear'
        else:
            img = source.image.copy()
            width = img.size[0]
            height = img.size[1]

        # Activate layer preview mode
        ori_layer_preview_mode = yp.layer_preview_mode
        yp.layer_preview_mode = True

        # Get neighbor mask
        neighbor_mask = layer.masks[neighbor_idx]

        # Disable modifiers
        #ori_mods = []
        #for i, mod in enumerate(mask.modifiers):
        #    ori_mods.append(mod.enable)
        #    mod.enable = False

        # Get layer tree
        tree = get_tree(layer)

        # Create mask mix nodes
        for m in [mask, neighbor_mask]:
            mix = new_node(tree, m, 'mix', 'ShaderNodeMixRGB', 'Mix')
            mix.blend_type = m.blend_type
            mix.inputs[0].default_value = m.intensity_value

        # Reconnect nodes
        rearrange_layer_nodes(layer)
        reconnect_layer_nodes(layer, merge_mask=True)

        # Prepare to bake
        self.scene = context.scene
        self.samples = 1
        self.margin = 5
        self.uv_map = mask.uv_name
        self.obj = obj

        remember_before_bake(self, context, yp)
        prepare_bake_settings(self, context, yp)

        # Get material output
        output = get_active_mat_output_node(mat.node_tree)
        ori_bsdf = output.inputs[0].links[0].from_socket

        # Create bake nodes
        tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
        emit = mat.node_tree.nodes.new('ShaderNodeEmission')

        # Set image
        tex.image = img
        mat.node_tree.nodes.active = tex

        # Connect
        mat.node_tree.links.new(node.outputs[LAYER_ALPHA_VIEWER], emit.inputs[0])
        mat.node_tree.links.new(emit.outputs[0], output.inputs[0])

        # Bake
        bpy.ops.object.bake()

        # Copy results to original image
        target_pxs = list(source.image.pixels)
        temp_pxs = list(img.pixels)

        if segment:
            start_x = width * segment.tile_x
            start_y = height * segment.tile_y
        else:
            start_x = 0
            start_y = 0

        for y in range(height):
            temp_offset_y = width * 4 * y
            offset_y = source.image.size[0] * 4 * (y + start_y)
            for x in range(width):
                temp_offset_x = 4 * x
                offset_x = 4 * (x + start_x)
                for i in range(3):
                    target_pxs[offset_y + offset_x + i] = temp_pxs[temp_offset_y + temp_offset_x + i]

        source.image.pixels = target_pxs

        # Remove temp image
        bpy.data.images.remove(img)

        # Remove mask mix nodes
        for m in [mask, neighbor_mask]:
            remove_node(tree, m, 'mix')

        # Remove modifiers
        for i, mod in reversed(list(enumerate(mask.modifiers))):
            MaskModifier.delete_modifier_nodes(tree, mod)
            mask.modifiers.remove(i)

        # Remove neighbor mask
        Mask.remove_mask(layer, neighbor_mask, obj)

        # Remove bake nodes
        simple_remove_node(mat.node_tree, tex)
        simple_remove_node(mat.node_tree, emit)

        # Recover original bsdf
        mat.node_tree.links.new(ori_bsdf, output.inputs[0])

        # Recover bake settings
        recover_bake_settings(self, context, yp)

        # Revert back preview mode 
        yp.layer_preview_mode = ori_layer_preview_mode

        # Set current mask as active
        mask.active_edit = True
        yp.active_layer_index = yp.active_layer_index

        return {'FINISHED'}

def temp_bake(context, entity, width, height, hdr, samples, margin, uv_map):

    m1 = re.match(r'yp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'yp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if not m1 and not m2: return

    yp = entity.id_data.yp
    obj = context.object
    #scene = context.scene

    # Prepare bake settings
    book = remember_before_bake_(yp)
    prepare_bake_settings_(book, [obj], yp, samples, margin, uv_map)

    mat = get_active_material()
    name = entity.name + ' Temp'

    # New target image
    image = bpy.data.images.new(name=name,
            width=width, height=height, alpha=True, float_buffer=hdr)
    image.colorspace_settings.name = 'Linear'

    if entity.type == 'HEMI':

        if m1: source = get_layer_source(entity)
        else: source = get_mask_source(entity)

        # Create bake nodes
        source_copy = mat.node_tree.nodes.new(source.bl_idname)
        source_copy.node_tree = source.node_tree

        tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
        emit = mat.node_tree.nodes.new('ShaderNodeEmission')
        output = get_active_mat_output_node(mat.node_tree)
        ori_bsdf = output.inputs[0].links[0].from_socket

        # Connect emit to output material
        mat.node_tree.links.new(emit.outputs[0], output.inputs[0])
        mat.node_tree.links.new(source_copy.outputs[0], output.inputs[0])

        # Set active texture
        tex.image = image
        mat.node_tree.nodes.active = tex

        # Bake
        bpy.ops.object.bake()

        # Recover link
        mat.node_tree.links.new(ori_bsdf, output.inputs[0])

        # Remove temp nodes
        mat.node_tree.nodes.remove(tex)
        simple_remove_node(mat.node_tree, emit)
        simple_remove_node(mat.node_tree, source_copy)

        # Set entity original type
        entity.original_type = 'HEMI'

    # Set entity flag
    entity.use_temp_bake = True

    # Recover bake settings
    recover_bake_settings_(book, yp)

    # Replace layer with temp image
    if m1: 
        Layer.replace_layer_type(entity, 'IMAGE', image.name, remove_data=True)
    else: Layer.replace_mask_type(entity, 'IMAGE', image.name, remove_data=True)

    # Set uv
    entity.uv_name = uv_map

    return image

def disable_temp_bake(entity):
    if not entity.use_temp_bake: return

    m1 = re.match(r'yp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'yp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    # Replace layer type
    if m1: Layer.replace_layer_type(entity, entity.original_type, remove_data=True)
    else: Layer.replace_mask_type(entity, entity.original_type, remove_data=True)

    # Set entity attribute
    entity.use_temp_bake = False


class YBakeTempImage(bpy.types.Operator):
    bl_idname = "node.y_bake_temp_image"
    bl_label = "Bake temporary image of layer"
    bl_description = "Bake temporary image of layer, can be useful to prefent glitch on cycles"
    bl_options = {'REGISTER', 'UNDO'}

    uv_map = StringProperty(default='')
    uv_map_coll = CollectionProperty(type=bpy.types.PropertyGroup)

    samples = IntProperty(name='Bake Samples', 
            description='Bake Samples, more means less jagged on generated textures', 
            default=1, min=1)

    margin = IntProperty(name='Bake Margin',
            description = 'Bake margin in pixels',
            default=5, subtype='PIXEL')

    width = IntProperty(name='Width', default = 1024, min=1, max=4096)
    height = IntProperty(name='Height', default = 1024, min=1, max=4096)

    hdr = BoolProperty(name='32 bit Float', default=True)

    @classmethod
    def poll(cls, context):
        return get_active_ypaint_node() #and hasattr(context, 'parent')

    def invoke(self, context, event):
        obj = context.object

        self.auto_cancel = False
        if not hasattr(context, 'parent'):
            self.auto_cancel = True
            return self.execute(context)

        self.parent = context.parent

        if self.parent.type not in {'HEMI'}:
            self.auto_cancel = True
            return self.execute(context)

        # Use active uv layer name by default
        uv_layers = get_uv_layers(obj)

        # UV Map collections update
        self.uv_map_coll.clear()
        for uv in uv_layers:
            if not uv.name.startswith(TEMP_UV):
                self.uv_map_coll.add().name = uv.name

        if len(self.uv_map_coll) > 0:
            self.uv_map = self.uv_map_coll[0].name

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        node = get_active_ypaint_node()
        yp = node.node_tree.yp

        if is_28():
            row = self.layout.split(factor=0.4)
        else: row = self.layout.split(percentage=0.4)

        col = row.column(align=False)

        #col.label(text='')
        col.label(text='Width:')
        col.label(text='Height:')
        col.label(text='')
        col.label(text='UV Map:')
        col.label(text='Samples:')
        col.label(text='Margin:')

        col = row.column(align=False)

        #col.prop(self, 'hdr')
        col.prop(self, 'width', text='')
        col.prop(self, 'height', text='')
        col.prop(self, 'hdr')
        col.prop_search(self, "uv_map", self, "uv_map_coll", text='', icon='GROUP_UVS')
        col.prop(self, 'samples', text='')
        col.prop(self, 'margin', text='')

    def execute(self, context):

        if not hasattr(self, 'parent'):
            self.report({'ERROR'}, "Context is incorrect!")
            return {'CANCELLED'}

        entity = self.parent
        if entity.type not in {'HEMI'}:
            self.report({'ERROR'}, "This layer type is not supported (yet)!")
            return {'CANCELLED'}

        # Bake temp image
        image = temp_bake(context, entity, self.width, self.height, self.hdr, self.samples , self.margin, self.uv_map)

        return {'FINISHED'}

class YDisableTempImage(bpy.types.Operator):
    bl_idname = "node.y_disable_temp_image"
    bl_label = "Disable Baked temporary image of layer"
    bl_description = "Disable bake temporary image of layer"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_active_ypaint_node() and hasattr(context, 'parent')

    def execute(self, context):
        entity = context.parent
        if not entity.use_temp_bake:
            self.report({'ERROR'}, "This layer is not temporarily baked!")
            return {'CANCELLED'}

        disable_temp_bake(entity)

        return {'FINISHED'}

def update_use_baked(self, context):
    tree = self.id_data
    yp = tree.yp

    if yp.halt_update: return

    # Check subdiv setup
    height_ch = get_root_height_channel(yp)
    if height_ch:
        check_subdiv_setup(height_ch)

    # Check uv nodes
    check_uv_nodes(yp)

    # Reconnect nodes
    rearrange_yp_nodes(tree)
    reconnect_yp_nodes(tree)

    # Trigger active image update
    if self.use_baked:
        self.active_channel_index = self.active_channel_index
    else:
        self.active_layer_index = self.active_layer_index

def check_subdiv_setup(height_ch):
    tree = height_ch.id_data
    yp = tree.yp

    if not height_ch: return
    obj = bpy.context.object
    mat = obj.active_material
    scene = bpy.context.scene

    # Get height image and max height
    baked_disp = tree.nodes.get(height_ch.baked_disp)
    end_max_height = tree.nodes.get(height_ch.end_max_height)
    if not baked_disp or not baked_disp.image or not end_max_height: return
    img = baked_disp.image
    max_height = end_max_height.outputs[0].default_value

    # Max height tweak node
    if yp.use_baked and height_ch.enable_subdiv_setup:
        end_max_height = check_new_node(tree, height_ch, 'end_max_height_tweak', 'ShaderNodeMath', 'Max Height Tweak')
        end_max_height.operation = 'MULTIPLY'
        end_max_height.inputs[1].default_value = height_ch.subdiv_tweak
    else:
        remove_node(tree, height_ch, 'end_max_height_tweak')

    # Subsurf
    subsurf = get_subsurf_modifier(obj)

    if yp.use_baked and height_ch.enable_subdiv_setup and not height_ch.subdiv_adaptive:

        if not subsurf:
            subsurf = obj.modifiers.new('Subsurf', 'SUBSURF')

        subsurf.render_levels = height_ch.subdiv_on_level
        subsurf.levels = height_ch.subdiv_on_level

    elif subsurf:
        subsurf.render_levels = height_ch.subdiv_off_level
        subsurf.levels = height_ch.subdiv_off_level

    # Set subsurf to visible
    if subsurf:
        subsurf.show_render = True
        subsurf.show_viewport = True

    # Displace
    if yp.use_baked and height_ch.enable_subdiv_setup and not height_ch.subdiv_adaptive:

        mod_len = len(obj.modifiers)

        displace = get_displace_modifier(obj)
        if not displace:
            displace = obj.modifiers.new('yP_Displace', 'DISPLACE')

            # Check modifier index
            for i, m in enumerate(obj.modifiers):
                if m == subsurf:
                    subsurf_idx = i
                elif m == displace:
                    displace_idx = i

            # Move up if displace is not directly below subsurf
            #if displace_idx != subsurf_idx+1:
            delta = displace_idx - subsurf_idx - 1
            for i in range(delta):
                bpy.ops.object.modifier_move_up(modifier=displace.name)

        tex = displace.texture
        if not tex:
            tex = bpy.data.textures.new(img.name, 'IMAGE')
            tex.image = img
            displace.texture = tex
            displace.texture_coords = 'UV'

        displace.strength = height_ch.subdiv_tweak * max_height
        displace.mid_level = height_ch.parallax_ref_plane
        displace.uv_layer = yp.baked_uv_name

        # Set displace to visible
        displace.show_render = True
        displace.show_viewport = True

    else:

        for mod in obj.modifiers:
            if mod.type == 'DISPLACE' and mod.name == 'yP_Displace':
                if mod.texture:
                    bpy.data.textures.remove(mod.texture)
                obj.modifiers.remove(mod)

    # Get active output material
    try: output_mat = [n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output][0]
    except: return

    # Get active ypaint node
    node = get_active_ypaint_node()
    norm_outp = node.outputs[height_ch.name]

    # Recover normal for Blender 2.7
    if not is_28():

        if not yp.use_baked or not height_ch.enable_subdiv_setup or (
                height_ch.enable_subdiv_setup and not height_ch.subdiv_adaptive):

            # Relink will only be proceed if no new links found
            link_found = any([l for l in norm_outp.links])
            if not link_found:

                # Try to relink to original connections
                for con in height_ch.ori_normal_to:
                    try:
                        node_to = mat.node_tree.nodes.get(con.node)
                        socket_to = node_to.inputs[con.socket]
                        if len(socket_to.links) < 1:
                            mat.node_tree.links.new(norm_outp, socket_to)
                    except: pass
                
            height_ch.ori_normal_to.clear()

    # Adaptive subdiv
    if yp.use_baked and height_ch.enable_subdiv_setup and height_ch.subdiv_adaptive:

        if not subsurf:
            subsurf = obj.modifiers.new('Subsurf', 'SUBSURF')
            subsurf.render_levels = height_ch.subdiv_off_level
            subsurf.levels = height_ch.subdiv_off_level

        # Adaptive subdivision only works for experimental feature set for now
        scene.cycles.feature_set = 'EXPERIMENTAL'
        scene.cycles.dicing_rate = height_ch.subdiv_global_dicing
        scene.cycles.preview_dicing_rate = height_ch.subdiv_global_dicing
        obj.cycles.use_adaptive_subdivision = True

        # Check output connection
        height_outp = node.outputs[height_ch.name + io_suffix['HEIGHT']]
        max_height_outp = node.outputs[height_ch.name + io_suffix['MAX_HEIGHT']]

        if is_28():
            #mat.cycles.displacement_method = 'BOTH'
            mat.cycles.displacement_method = 'DISPLACEMENT'

            # Search for displacement node
            height_matches = []
            for link in height_outp.links:
                if link.to_node.type == 'DISPLACEMENT':
                    #disp = link.to_node
                    height_matches.append(link.to_node)

            max_height_matches = []
            for link in max_height_outp.links:
                if link.to_node.type == 'DISPLACEMENT':
                    max_height_matches.append(link.to_node)

            disp = None
            for n in height_matches:
                if n in max_height_matches:
                    disp = n
                    break

            # Create one if there's none
            if not disp:
                disp = mat.node_tree.nodes.new('ShaderNodeDisplacement')
                disp.location.x = node.location.x #+ 200
                disp.location.y = node.location.y - 400

            create_link(mat.node_tree, disp.outputs[0], output_mat.inputs['Displacement'])
            create_link(mat.node_tree, height_outp, disp.inputs['Height'])
            create_link(mat.node_tree, max_height_outp, disp.inputs['Scale'])

        else:
            # Remember normal connection, because it will be disconnected to avoid render error
            for link in norm_outp.links:
                con = height_ch.ori_normal_to.add()
                con.node = link.to_node.name
                con.socket = link.to_socket.name

            # Remove normal connection because it will produce render error
            break_output_link(mat.node_tree, norm_outp)

            # Set displacement mode
            #mat.cycles.displacement_method = 'BOTH'
            mat.cycles.displacement_method = 'TRUE'

            # Search for displacement node
            height_matches = []
            for link in height_outp.links:
                #if link.to_node.type == 'MATH' and link.to_node.operation == 'MULTIPLY':
                if link.to_node.type == 'GROUP' and link.to_node.node_tree.name == lib.BL27_DISP:
                    #disp = link.to_node
                    height_matches.append(link.to_node)

            max_height_matches = []
            for link in max_height_outp.links:
                #if link.to_node.type == 'MATH' and link.to_node.operation == 'MULTIPLY':
                if link.to_node.type == 'GROUP' and link.to_node.node_tree.name == lib.BL27_DISP:
                    max_height_matches.append(link.to_node)

            disp = None
            for n in height_matches:
                if n in max_height_matches:
                    disp = n
                    break

            # Create one if there's none
            if not disp:
                #disp = mat.node_tree.nodes.new('ShaderNodeMath')
                #disp.operation = 'MULTIPLY'
                disp = mat.node_tree.nodes.new('ShaderNodeGroup')
                disp.node_tree = get_node_tree_lib(lib.BL27_DISP)
                disp.location.x = node.location.x #+ 200
                disp.location.y = node.location.y - 400

            create_link(mat.node_tree, disp.outputs[0], output_mat.inputs['Displacement'])
            create_link(mat.node_tree, height_outp, disp.inputs[0])
            create_link(mat.node_tree, max_height_outp, disp.inputs[1])

    else:
        obj.cycles.use_adaptive_subdivision = False

        # Back to supported feature set
        # NOTE: It's kinda forced, but whatever
        #scene.cycles.feature_set = 'SUPPORTED'

        # Remove displacement output material link
        # NOTE: It's very forced, but whatever
        break_input_link(mat.node_tree, output_mat.inputs['Displacement'])

def update_enable_subdiv_setup(self, context):
    obj = context.object
    tree = self.id_data
    yp = tree.yp

    # Check uv nodes to enable/disable parallax
    check_uv_nodes(yp)

    # Check subdiv setup
    check_subdiv_setup(self)

    # Reconnect nodes
    rearrange_yp_nodes(tree)
    reconnect_yp_nodes(tree)

def update_subdiv_tweak(self, context):
    obj = context.object
    tree = self.id_data
    yp = tree.yp

    height_ch = self

    displace = get_displace_modifier(obj)
    if displace:
        end_max_height = tree.nodes.get(height_ch.end_max_height)
        if end_max_height:
            displace.strength = height_ch.subdiv_tweak * end_max_height.outputs[0].default_value

    end_max_height_tweak = tree.nodes.get(height_ch.end_max_height_tweak)
    if end_max_height_tweak:
        end_max_height_tweak.inputs[1].default_value = height_ch.subdiv_tweak

def update_subdiv_on_off_level(self, context):
    obj = context.object
    tree = self.id_data
    yp = tree.yp

    height_ch = self

    subsurf = get_subsurf_modifier(obj)
    if not subsurf: return

    if self.enable_subdiv_setup and yp.use_baked and not self.subdiv_adaptive:
        subsurf.render_levels = height_ch.subdiv_on_level
        subsurf.levels = height_ch.subdiv_on_level
    else:
        subsurf.render_levels = height_ch.subdiv_off_level
        subsurf.levels = height_ch.subdiv_off_level

def update_subdiv_standard_type(self, context):
    obj = context.object
    tree = self.id_data
    yp = tree.yp

    height_ch = self

    subsurf = get_subsurf_modifier(obj)
    if not subsurf: return

    subsurf.subdivision_type = height_ch.subdiv_standard_type

def update_subdiv_global_dicing(self, context):
    scene = context.scene
    height_ch = self

    scene.cycles.dicing_rate = height_ch.subdiv_global_dicing
    scene.cycles.preview_dicing_rate = height_ch.subdiv_global_dicing

def register():
    bpy.utils.register_class(YTransferSomeLayerUV)
    bpy.utils.register_class(YTransferLayerUV)
    bpy.utils.register_class(YResizeImage)
    bpy.utils.register_class(YBakeChannels)
    bpy.utils.register_class(YMergeLayer)
    bpy.utils.register_class(YMergeMask)
    bpy.utils.register_class(YBakeTempImage)
    bpy.utils.register_class(YDisableTempImage)

def unregister():
    bpy.utils.unregister_class(YTransferSomeLayerUV)
    bpy.utils.unregister_class(YTransferLayerUV)
    bpy.utils.unregister_class(YResizeImage)
    bpy.utils.unregister_class(YBakeChannels)
    bpy.utils.unregister_class(YMergeLayer)
    bpy.utils.unregister_class(YMergeMask)
    bpy.utils.unregister_class(YBakeTempImage)
    bpy.utils.unregister_class(YDisableTempImage)
