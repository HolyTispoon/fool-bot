extends SceneTree

## The first picture: Godot plays a few answers against the AI, then
## draws the position from the wire's own layout -- the spaces, the
## meeple's outline, the fans, the colours, what is lit, a card -- and
## saves a picture of the window. Nothing about the game is typed here.
##
##   godot --path docs/godot/spike --resolution 1280x720 --script res://board.gd -- \
##       <python> <repo> <folder> <out.png>
##
## It needs a window (a headless run draws no frame), and is laid out
## for 1280x720 only: a spike, not a layout.

const Wire := preload("res://wire.gd")

const GOLD := "#f0b232"
const PAGE := "#313338"
const PANEL := "#2b2d31"
const DEEP := "#1e1f22"
const TEXT := "#dbdee1"
const MUTED := "#949ba4"
const LINE := "#3f4147"
## The picture is taken at the first of these asked after nine answers:
## the prompts whose answers are things on the field.
const STOP_ON := ["maneuver_challenge", "low_pass_choice", "run_back_space", "ball_handler_selection", "shooter_choice"]

var wire: Wire
var display_font: FontFile
var board_font: FontFile
var meeple_textures := {}
var species_textures := {}


func _initialize() -> void:
	create_timer(80.0).timeout.connect(func() -> void:
		print("GAVE UP after 80s")
		wire.stop()
		quit(3))
	wire = Wire.new()
	root.add_child(wire)
	_run.call_deferred()


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	if not await wire.start(args[0], args[1], args[2]):
		print("the server never answered: see sidecar.log in ", args[2])
		quit(1)
		return
	var id := await wire.open_room_against_the_ai("teal")

	var state: Variant = null
	var answered := 0
	while answered < 45:
		state = await wire.api(HTTPClient.METHOD_GET, "/api/game/%s" % id)
		var prompt: Variant = state["prompt"]
		if prompt == null or prompt["state"] == "full_time":
			break
		if prompt["state"] == "waiting":
			await create_timer(0.2).timeout
			continue
		if answered >= 9 and prompt["state"] == "yours" and STOP_ON.has(prompt["kind"]):
			break
		var controls := Wire.usable(prompt)
		if controls.is_empty():
			break
		await wire.api(HTTPClient.METHOD_POST, "/api/game/%s/action" % id,
			Wire.body_for(Wire.pick(prompt["kind"], controls)))
		answered += 1
	print("answered ", answered, " before the picture")

	# The bundled faces, fetched from the server that serves them to the
	# page. The game itself would ship them; the spike has nothing to ship.
	display_font = FontFile.new()
	display_font.data = await wire.fetch("/fonts/RacingSansOne-Regular.ttf")
	board_font = FontFile.new()
	board_font.data = await wire.fetch("/fonts/RobotoSlab-Bold.ttf")

	await draw(state, id)
	for _frame in 6:
		await process_frame
	# A window that is covered, hidden or on a sleeping screen is never
	# drawn, so there may be no frame to wait for: draw one on demand.
	RenderingServer.force_draw(false)
	var image := root.get_texture().get_image()
	print("saved ", args[3], " ", image.get_width(), "x", image.get_height(), ": ", error_string(image.save_png(args[3])))
	wire.stop()
	quit(0)


# -- small helpers ------------------------------------------------------

func label(text: String, size: int, colour: String, font: FontFile = null) -> Label:
	var made := Label.new()
	made.text = text
	made.add_theme_font_size_override("font_size", size)
	made.add_theme_color_override("font_color", Color(colour))
	made.add_theme_font_override("font", font if font != null else board_font)
	return made


func box(fill: String, edge: String, edge_width: int, radius: int) -> StyleBoxFlat:
	var made := StyleBoxFlat.new()
	made.bg_color = Color(fill)
	made.border_color = Color(edge)
	made.set_border_width_all(edge_width)
	made.set_corner_radius_all(radius)
	return made


func panel(parent: Node, at: Vector2, size: Vector2, style: StyleBoxFlat) -> Panel:
	var made := Panel.new()
	made.position = at
	made.size = size
	made.add_theme_stylebox_override("panel", style)
	parent.add_child(made)
	return made


func place(parent: Node, node: Control, at: Vector2, size: Vector2 = Vector2.ZERO, centred := false) -> void:
	node.position = at
	if size != Vector2.ZERO:
		node.size = size
	if centred and node is Label:
		(node as Label).horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	parent.add_child(node)


## The wire sends sentences as HTML today, so a spike strips the tags.
## Step 1 of the worksheet is what makes this function unnecessary.
func plain(html: String) -> String:
	var tags := RegEx.new()
	tags.compile("<[^>]*>")
	return tags.sub(html, "", true).replace("&#x27;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


# -- the pieces ---------------------------------------------------------

## The meeple, from the outline the wire serves (`render.MEEPLE_PATH`),
## drawn by Godot's own SVG rasteriser at three times the size shown.
func meeple_texture(geometry: Dictionary, fill: String, edge: String, edge_scale: float) -> Texture2D:
	var key := fill + edge + str(edge_scale)
	if meeple_textures.has(key):
		return meeple_textures[key]
	var bounds: Array = geometry["box"]
	var stroke: float = float(geometry["stroke"]) * edge_scale
	var width := float(geometry["width"])
	var height: float = width * float(bounds[3]) / float(bounds[2])
	var svg := "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"%f\" height=\"%f\" viewBox=\"%f %f %f %f\"><path d=\"%s\" fill=\"%s\" stroke=\"%s\" stroke-width=\"%f\" stroke-linejoin=\"round\"/></svg>" % [
		width, height,
		float(bounds[0]) - stroke, float(bounds[1]) - stroke, float(bounds[2]) + 2 * stroke, float(bounds[3]) + 2 * stroke,
		geometry["path"], fill, edge, stroke]
	var image := Image.new()
	var loaded := image.load_svg_from_string(svg, 3.0)
	if loaded != OK:
		print("the meeple's outline did not load: ", error_string(loaded))
	var texture := ImageTexture.create_from_image(image)
	meeple_textures[key] = texture
	return texture


## A species icon: the served silhouette, in the ink the wire names.
func species_texture(species: String, ink: String) -> Texture2D:
	var key := species + ink
	if species_textures.has(key):
		return species_textures[key]
	var image := Image.new()
	if image.load_png_from_buffer(await wire.fetch("/species/%s.png" % species)) != OK:
		return null
	image.resize(72, 72, Image.INTERPOLATE_LANCZOS)
	image.convert(Image.FORMAT_RGBA8)
	var tint := Color(ink)
	for y in image.get_height():
		for x in image.get_width():
			image.set_pixel(x, y, Color(tint.r, tint.g, tint.b, image.get_pixel(x, y).a))
	var texture := ImageTexture.create_from_image(image)
	species_textures[key] = texture
	return texture


func draw_meeple(parent: Node, piece: Dictionary, geometry: Dictionary, at: Vector2, lit: bool, with_species: bool) -> void:
	var width := float(geometry["width"])
	var bounds: Array = geometry["box"]
	var height: float = width * float(bounds[3]) / float(bounds[2])
	var art := TextureRect.new()
	art.texture = meeple_texture(geometry, piece["colour"], GOLD if lit else "#111214", 1.6 if lit else 1.0)
	art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	art.stretch_mode = TextureRect.STRETCH_SCALE
	place(parent, art, at, Vector2(width, height))
	if with_species and piece.get("species") != null:
		var icon_size: float = width * float(geometry["icon_size"])
		var icon := TextureRect.new()
		icon.texture = await species_texture(piece["species"], piece["ink"])
		icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		icon.stretch_mode = TextureRect.STRETCH_SCALE
		place(parent, icon, at + Vector2((width - icon_size) / 2.0, height * float(geometry["icon_center"]) - icon_size / 2.0), Vector2(icon_size, icon_size))
	var centre: float = float(geometry["role_center"]) if with_species else float(geometry["solo_center"])
	var letters := label(piece["role"], int(round(width * float(geometry["role_font"]))), piece["ink"])
	place(parent, letters, at + Vector2(0, height * centre - 9.0), Vector2(width, 18), true)


## The d12 seen face-on, as the page draws it: a ten-sided outline.
func decagon(parent: Node, centre: Vector2, radius: float, fill: String, text: String, ink: String, size: int) -> void:
	var shape := Polygon2D.new()
	var points := PackedVector2Array()
	for corner in 10:
		var angle := TAU * corner / 10.0 - PI / 2.0
		points.append(centre + Vector2(cos(angle), sin(angle)) * radius)
	shape.polygon = points
	shape.color = Color(fill)
	parent.add_child(shape)
	place(parent, label(text, size, ink), centre - Vector2(radius, size * 0.72), Vector2(radius * 2.0, size * 1.4), true)


## A dodecahedron from its twenty vertices (`d12ball/dice.py` holds the
## same solid): each face is the five corners nearest one of the twelve
## face directions, walked round and cut into three triangles.
func dodecahedron() -> ArrayMesh:
	var phi := (1.0 + sqrt(5.0)) / 2.0
	var corners: Array[Vector3] = []
	var directions: Array[Vector3] = []
	for x: float in [-1.0, 1.0]:
		for y: float in [-1.0, 1.0]:
			for z: float in [-1.0, 1.0]:
				corners.append(Vector3(x, y, z))
	for a: float in [-1.0, 1.0]:
		for b: float in [-1.0, 1.0]:
			corners.append(Vector3(0, a / phi, b * phi))
			corners.append(Vector3(a / phi, b * phi, 0))
			corners.append(Vector3(a * phi, 0, b / phi))
			directions.append(Vector3(a, 0, b * phi).normalized())
			directions.append(Vector3(0, a * phi, b).normalized())
			directions.append(Vector3(a * phi, b, 0).normalized())
	var tool := SurfaceTool.new()
	tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	for normal: Vector3 in directions:
		var ranked := corners.duplicate()
		ranked.sort_custom(func(one: Vector3, other: Vector3) -> bool: return one.dot(normal) > other.dot(normal))
		var face: Array = ranked.slice(0, 5)
		var middle := Vector3.ZERO
		for corner: Vector3 in face:
			middle += corner / 5.0
		var first: Vector3 = face[0]
		var across: Vector3 = (first - middle).normalized()
		var up: Vector3 = normal.cross(across)
		face.sort_custom(func(one: Vector3, other: Vector3) -> bool:
			return atan2((one - middle).dot(up), (one - middle).dot(across)) < atan2((other - middle).dot(up), (other - middle).dot(across)))
		for step in range(1, 4):
			# Godot's front faces wind clockwise seen from outside.
			for corner: Vector3 in [face[0], face[step + 1], face[step]]:
				tool.set_normal(normal)
				tool.add_vertex(corner)
	return tool.commit()


## The solid over the flat page: a transparent 3D viewport in the 2D tree.
func draw_die(parent: Node, at: Vector2, size: float, colour: String) -> void:
	var holder := SubViewportContainer.new()
	holder.stretch = true
	place(parent, holder, at, Vector2(size, size))
	var view := SubViewport.new()
	view.transparent_bg = true
	view.own_world_3d = true
	view.size = Vector2i(int(size), int(size))
	holder.add_child(view)
	var solid := MeshInstance3D.new()
	solid.mesh = dodecahedron()
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(colour)
	material.roughness = 0.3
	material.metallic = 0.1
	solid.material_override = material
	# One face up: the face direction (0, phi, 1) turned onto the y axis.
	solid.rotation_degrees = Vector3(-31.72, 24, 0)
	view.add_child(solid)
	var camera := Camera3D.new()
	camera.position = Vector3(0, 3.1, 4.4)
	camera.rotation_degrees = Vector3(-35, 0, 0)
	camera.fov = 40
	view.add_child(camera)
	var key := DirectionalLight3D.new()
	key.rotation_degrees = Vector3(-55, 35, 0)
	key.light_energy = 1.3
	view.add_child(key)
	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-15, -120, 0)
	fill.light_energy = 0.5
	view.add_child(fill)


# -- the picture --------------------------------------------------------

func draw(state: Dictionary, id: String) -> void:
	var layout: Dictionary = state["board"]["layout"]
	var prompt: Variant = state["prompt"]
	var jumbotron: Dictionary = layout["jumbotron"]
	var geometry: Dictionary = layout["meeple"]
	var with_species: bool = layout["species_icons"]
	var home: Dictionary = jumbotron["home"]
	var visiting: Dictionary = jumbotron["visiting"]

	# What is lit, straight off the places the controls name.
	var lit_players := {}
	var lit_spaces := {}
	var lit_ball := false
	var offered := []
	if prompt != null:
		offered = Wire.usable(prompt)
		for control: Dictionary in offered:
			var where: Variant = control.get("place")
			if where == null:
				continue
			if where["at"] == "player":
				lit_players[where["id"]] = true
			elif where["at"] == "space":
				lit_spaces["%s/%d" % [where["zone"], int(where["space_index"])]] = true
			elif where["at"] == "ball":
				lit_ball = true

	var ground := ColorRect.new()
	ground.color = Color(PAGE)
	ground.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_child(ground)

	# The jumbotron: one bar.
	var bar := panel(root, Vector2(24, 14), Vector2(1232, 84), box(DEEP, LINE, 1, 12))
	place(bar, label(str(home["name"]).to_upper(), 30, home["colour"], display_font), Vector2(22, 12), Vector2(360, 40))
	place(bar, label("HOME" + ("  ·  BALL" if home["possession"] else ""), 12, MUTED), Vector2(24, 54), Vector2(360, 18))
	var away := label(str(visiting["name"]).to_upper(), 30, visiting["colour"], display_font)
	away.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	place(bar, away, Vector2(850, 12), Vector2(360, 40))
	var away_note := label(("BALL  ·  " if visiting["possession"] else "") + "VISITORS", 12, MUTED)
	away_note.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	place(bar, away_note, Vector2(850, 54), Vector2(358, 18))
	place(bar, label("%d  –  %d" % [int(jumbotron["score"]["home"]), int(jumbotron["score"]["visiting"])], 40, TEXT, display_font), Vector2(416, 2), Vector2(400, 52), true)
	place(bar, label("minute %s  ·  %s" % [jumbotron["minute"], jumbotron["half"]], 14, "#f5d76e"), Vector2(416, 54), Vector2(400, 20), true)

	# The field: a goal at each end, the spaces between, the zones above.
	var stage := panel(root, Vector2(24, 110), Vector2(940, 402), box(DEEP, LINE, 1, 14))
	var spaces: Array = layout["spaces"]
	var goal_width := 54.0
	var gap := 6.0
	var top := 40.0
	var tall := 346.0
	var space_width: float = (940.0 - 2 * 12.0 - 2 * goal_width - gap * (spaces.size() + 1)) / spaces.size()
	for end: Array in [[home, 12.0], [visiting, 940.0 - 12.0 - goal_width]]:
		var slab := panel(stage, Vector2(end[1], top), Vector2(goal_width, tall), box("#0c141c", end[0]["colour"], 3, 8))
		var letters := "GOAL"
		for index in letters.length():
			place(slab, label(letters[index], 34, TEXT, display_font), Vector2(0, 62 + index * 56), Vector2(goal_width, 44), true)

	var zone_x := 12.0 + goal_width + gap
	for zone: Dictionary in layout["zones"]:
		var count := int(zone["spaces"])
		var zone_width: float = space_width * count + gap * (count - 1)
		place(stage, label(zone["label"], 17, MUTED, display_font), Vector2(zone_x, 10), Vector2(zone_width, 24), true)
		zone_x += zone_width + gap

	var ball_at := Vector2.ZERO
	var ball_speed := ""
	for number in spaces.size():
		var space: Dictionary = spaces[number]
		var left: float = 12.0 + goal_width + gap + number * (space_width + gap)
		var lit: bool = lit_spaces.has("%s/%d" % [space["zone"], int(space["index"])])
		var cell := panel(stage, Vector2(left, top), Vector2(space_width, tall), box(PANEL, GOLD if lit else LINE, 3 if lit else 1, 8))
		if space["tint"] != null:
			var wash := ColorRect.new()
			var tint := Color(str(space["tint"]))
			wash.color = Color(tint.r, tint.g, tint.b, 0.12)
			place(cell, wash, Vector2(2, 2), Vector2(space_width - 4, tall - 4))
		place(cell, label(str(space["code"]), 13, MUTED), Vector2(8, 5), Vector2(30, 18))
		# The visitors' lane on top, home's below; each fan where the
		# wire put it, in units of a meeple fifty wide.
		for lane_name: String in ["visiting", "home"]:
			var lane_top: float = 30.0 if lane_name == "visiting" else 190.0
			var fan: Dictionary = space["fans"][lane_name]
			var pieces: Array = fan["pieces"]
			if pieces.is_empty():
				continue
			var origin := Vector2((space_width - float(fan["width"])) / 2.0, lane_top)
			var lowest := 0.0
			for piece: Dictionary in pieces:
				var at := origin + Vector2(float(piece["x"]), float(piece["y"]))
				await draw_meeple(cell, piece, geometry, at, lit_players.has(piece["id"]), with_species)
				lowest = maxf(lowest, float(piece["y"]))
				if piece.get("exhaustion") != null:
					place(cell, label("z×%d" % int(piece["exhaustion"]["count"]), 10, "#f5d76e"), at + Vector2(34, 36), Vector2(40, 14))
			var names: Array = fan["names"]
			for row in names.size():
				for piece: Dictionary in pieces:
					if piece["id"] == names[row]:
						place(cell, label(piece["name"], 11, GOLD if lit_players.has(piece["id"]) else TEXT), Vector2(0, lane_top + lowest + 50 + row * 14), Vector2(space_width, 14), true)
		if space["ball"] != null:
			var ball: Dictionary = space["ball"]
			ball_speed = str(int(ball["speed"]))
			if ball["holder"] == null:
				ball_at = Vector2(left + space_width / 2.0, top + tall / 2.0)
			else:
				var fan_width := float(space["fans"][ball["side"]]["width"])
				var corner := Vector2((space_width + fan_width) / 2.0 + 2.0, 186.0) if ball["side"] == "home" else Vector2((space_width - fan_width) / 2.0 - 2.0, 74.0)
				ball_at = Vector2(left, top) + corner
	if ball_at != Vector2.ZERO:
		decagon(stage, ball_at, 19.0, GOLD if lit_ball else "#111214", "", TEXT, 12)
		decagon(stage, ball_at, 15.0, "#ffffff", ball_speed, "#243347", 15)

	# The question box: what is asked and what is lit, in the wire's words.
	var asked: bool = prompt != null and prompt["state"] == "yours"
	var question := panel(root, Vector2(24, 524), Vector2(940, 182), box(PANEL, GOLD if asked else LINE, 2, 12))
	if prompt != null:
		place(question, label(str(prompt["state"]).to_upper().replace("_", " ") + "  ·  " + str(prompt["kind"]), 12, GOLD), Vector2(18, 12), Vector2(900, 16))
		var ask := label(plain(prompt["ask"]), 17, TEXT)
		ask.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		place(question, ask, Vector2(18, 34), Vector2(900, 50))
		var row := 0
		for control: Dictionary in offered.slice(0, 8):
			var where: Variant = control.get("place")
			var mark: String = "lights the %s" % where["at"] if where != null else "a plain control"
			place(question, label("•  %s   (%s)" % [control.get("label", "?"), mark], 13, MUTED), Vector2(18 + (row % 2) * 450, 92 + (row / 2) * 20), Vector2(440, 18))
			row += 1

	# Beside the field: one of the model's own cards, and the ball as a solid.
	var side := panel(root, Vector2(980, 110), Vector2(276, 596), box(DEEP, LINE, 1, 14))
	var card_id: String = layout["zones"][0]["home"][0]["id"]
	for space: Dictionary in spaces:
		if space["ball"] != null and space["ball"]["holder"] != null:
			card_id = space["ball"]["holder"]
	var card_image := Image.new()
	if card_image.load_png_from_buffer(await wire.fetch("/api/game/%s/card/%s.png?face=full" % [id, card_id])) == OK:
		var card := TextureRect.new()
		card.texture = ImageTexture.create_from_image(card_image)
		card.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		card.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		place(side, card, Vector2(18, 16), Vector2(240, 336))
	place(side, label("the model's own card, as served", 11, MUTED), Vector2(0, 356), Vector2(276, 16), true)
	draw_die(side, Vector2(48, 384), 180.0, home["colour"] if home["possession"] else visiting["colour"])
	place(side, label("a d12 built from its twenty vertices", 11, MUTED), Vector2(0, 566), Vector2(276, 16), true)
