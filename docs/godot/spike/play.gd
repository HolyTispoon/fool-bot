extends SceneTree

## Godot plays D12 Ball against the AI through the web app's wire, with
## nothing but what the wire hands it: it starts the server as a child
## process, sets the table, and answers what it is asked.
##
##   godot --headless --path docs/godot/spike --script res://play.gd -- \
##       <python> <repo> <folder> [answers]
##
## <python> needs requirements.txt installed; <folder> is where the
## server keeps its files (a temporary one -- never the checkout's data/).

const Wire := preload("res://wire.gd")

var wire: Wire


func _initialize() -> void:
	create_timer(110.0).timeout.connect(func() -> void:
		print("GAVE UP after 110s")
		wire.stop()
		quit(3))
	wire = Wire.new()
	root.add_child(wire)
	_run.call_deferred()


func _run() -> void:
	var args := OS.get_cmdline_user_args()
	var budget := int(args[3]) if args.size() > 3 else 40
	var began := Time.get_ticks_msec()
	if not await wire.start(args[0], args[1], args[2]):
		print("the server never answered: see sidecar.log in ", args[2])
		quit(1)
		return
	print("the server answered ", Time.get_ticks_msec() - began, " ms after it was started")

	var id := await wire.open_room_against_the_ai()
	var since := 0
	var answered := 0
	var kinds := {}
	var state: Variant = null
	while answered < budget:
		state = await wire.api(HTTPClient.METHOD_GET, "/api/game/%s?since=%d" % [id, since])
		since = int(state["latest"])
		var prompt: Variant = state["prompt"]
		if prompt == null or prompt["state"] == "full_time":
			break
		if prompt["state"] == "waiting":
			await create_timer(0.2).timeout
			continue
		var controls := Wire.usable(prompt)
		if controls.is_empty():
			break
		var kind: String = prompt["kind"]
		if not kinds.has(kind):
			kinds[kind] = true
			var lights := {}
			for control: Dictionary in controls:
				var where: Variant = control.get("place")
				lights[where["at"] if where != null else "(plain)"] = true
			print("  first sight of ", kind, " [", prompt["state"], "], lighting ", lights.keys())
		var control := Wire.pick(kind, controls)
		var after: Variant = await wire.api(HTTPClient.METHOD_POST,
			"/api/game/%s/action?since=%d" % [id, since], Wire.body_for(control))
		answered += 1
		var note := ""
		if after == null:
			note = " -- not JSON"
		else:
			since = int(after["latest"])
			if after.get("refusal") != null:
				note += ", REFUSED: " + str(after["refusal"]).substr(0, 80)
			if after.get("roll") != null:
				var faces := []
				for one: Dictionary in after["roll"]["dice"]:
					faces.append(int(one["face"]))
				note += ", roll %s %s" % [after["roll"]["shape"], faces]
		var where: Variant = control.get("place")
		print("%3d %-22s %-28s @%-10s -> %d%s" % [answered, kind,
			str(control.get("label", "?")).substr(0, 28),
			where["at"] if where != null else "(plain)", wire.status, note])

	if state != null and state.get("scoreboard") != null:
		var score: Dictionary = state["scoreboard"]
		print("stopped at %d-%d, minute %d, %s" % [int(score["home"]), int(score["visiting"]), int(score["minute"]), score["period"]])
	print("kinds answered: ", kinds.keys())

	# The trap, last: one control sent back as Godot's JSON writes it.
	state = await wire.api(HTTPClient.METHOD_GET, "/api/game/%s?since=%d" % [id, since])
	if state["prompt"] != null:
		for control: Dictionary in Wire.usable(state["prompt"]):
			var as_godot_writes := JSON.stringify({"action": control["action"]})
			if control["type"] == "button" and as_godot_writes.contains(".0"):
				await wire.fetch("/api/game/%s/action" % id, HTTPClient.METHOD_POST, as_godot_writes)
				print("sent as Godot's JSON writes it: ", as_godot_writes.substr(0, 150))
				print("  -> ", wire.status)
				break

	wire.spent_ms.sort()
	print("requests: ", wire.spent_ms.size(), ", median ", wire.spent_ms[wire.spent_ms.size() / 2],
		" ms, slowest ", wire.spent_ms[-1], " ms")
	print("the server left on its own: ", wire.stop())
	quit(0)
