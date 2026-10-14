extends Node

## The spike's whole client: the web app started as a child process, one
## cookie, JSON in and out, and the answers a prompt offers read off it
## as the wire wrote them. Nothing here knows a rule.

var base := ""
var cookie := ""
var status := 0
var spent_ms: Array[int] = []

var _http: HTTPRequest
var _pid := -1
var _stdio: FileAccess
var _stderr: FileAccess


## Start `sidecar.py` under `python`, serving `repo`'s web app over
## `folder`, and wait until it answers. False if it never does.
func start(python: String, repo: String, folder: String) -> bool:
	var launcher := ProjectSettings.globalize_path("res://sidecar.py")
	var info := OS.execute_with_pipe(python, [launcher, repo, folder])
	if info.is_empty():
		return false
	_pid = info["pid"]
	_stdio = info["stdio"]
	_stderr = info["stderr"]
	var announce: Variant = JSON.parse_string(_stdio.get_line())
	if not announce is Dictionary:
		return false
	base = "http://127.0.0.1:%d" % int(announce["port"])
	_http = HTTPRequest.new()
	_http.timeout = 20.0
	add_child(_http)
	for attempt in 100:
		if await api(HTTPClient.METHOD_GET, "/api/me") != null:
			return true
		await get_tree().create_timer(0.15).timeout
	return false


## Let go of the child. True if it left on its own when the pipe closed.
func stop() -> bool:
	if _stdio != null:
		_stdio.close()
		_stdio = null
	if _stderr != null:
		_stderr.close()
		_stderr = null
	if _pid <= 0 or not OS.is_process_running(_pid):
		return true
	OS.delay_msec(600)
	if not OS.is_process_running(_pid):
		return true
	OS.kill(_pid)
	return false


func fetch(path: String, method := HTTPClient.METHOD_GET, body := "") -> PackedByteArray:
	var headers := PackedStringArray()
	if cookie != "":
		# Godot keeps no cookie jar: the one cookie is resent by hand.
		headers.append("Cookie: " + cookie)
	if body != "":
		headers.append("Content-Type: application/json")
	var began := Time.get_ticks_msec()
	if _http.request(base + path, headers, method, body) != OK:
		status = 0
		return PackedByteArray()
	var done: Array = await _http.request_completed
	spent_ms.append(Time.get_ticks_msec() - began)
	status = done[1]
	for header: String in done[2]:
		if header.to_lower().begins_with("set-cookie:"):
			cookie = header.substr(11).strip_edges().split(";")[0]
	return done[3]


## One request, answered as parsed JSON -- or null where the answer was
## not JSON (the server's plain-text errors, or nobody there).
func api(method: int, path: String, body: Variant = null) -> Variant:
	var sent := "" if body == null else JSON.stringify(body)
	var text := (await fetch(path, method, sent)).get_string_from_utf8()
	if text.begins_with("{") or text.begins_with("["):
		return JSON.parse_string(text)
	return null


## Godot reads every JSON number as a float and writes 3 back as 3.0,
## which the server answers with a 500. An action's numbers are whole
## numbers, and go back as such.
static func whole(value: Variant) -> Variant:
	if value is float:
		return int(value) if value == floorf(value) else value
	if value is Array:
		var items := []
		for item: Variant in value:
			items.append(whole(item))
		return items
	if value is Dictionary:
		var entries := {}
		for key: Variant in value:
			entries[key] = whole(value[key])
		return entries
	return value


## Every control of a prompt that may be pressed, in the wire's order.
static func usable(prompt: Dictionary) -> Array:
	var found := []
	for section: Dictionary in prompt.get("controls", []):
		for control: Dictionary in section.get("controls", []):
			if control.get("post") != null:
				continue
			if control["type"] == "button" and control.get("disabled", false):
				continue
			found.append(control)
	return found


## Which control the spike presses: a window's whistle, otherwise the
## first one offered. A stand-in for a person, not a policy.
static func pick(kind: String, controls: Array) -> Dictionary:
	if kind.begins_with("coaching") or kind == "halftime_extra_token":
		for control: Dictionary in controls:
			var place: Variant = control.get("place")
			if place != null and place["at"] == "whistle":
				return control
		return controls[-1]
	return controls[0]


## What pressing `control` posts: its own action, numbers made whole,
## and a chooser's first choice in each field.
static func body_for(control: Dictionary) -> Dictionary:
	var action: Dictionary = whole(control["action"])
	if control["type"] == "chooser":
		for field: Dictionary in control["fields"]:
			action["arguments"][field["name"]] = field["choices"][0]["value"]
	return {"action": action}


## A room against the AI, set up through the table's own moves, to the
## first prompt. Returns the room's id.
func open_room_against_the_ai(team_key := "") -> String:
	var room: Dictionary = await api(HTTPClient.METHOD_POST, "/api/rooms", {})
	var id: String = room["id"]
	var state: Variant = await api(HTTPClient.METHOD_POST, "/api/room/%s/seat/ai" % id, {"seat": 2})
	for seat: Dictionary in state["table"]["seats"]:
		if seat["picks_itself"] or seat["team"] != null:
			continue
		for team: Dictionary in seat["teams"]:
			if not (team["offered"] and team["open"]) or team["picked"]:
				continue
			if team_key != "" and team["key"] != team_key:
				continue
			state = await api(HTTPClient.METHOD_POST, "/api/room/%s/table/pick_team" % id,
				{"team": team["key"], "seat": int(seat["number"])})
			break
	state = await api(HTTPClient.METHOD_POST, "/api/room/%s/table/flip_coin" % id)
	if state.get("table") != null and state["table"]["sides"]["may"]:
		await api(HTTPClient.METHOD_POST, "/api/room/%s/table/choose" % id, {"choice": "home"})
	return id
