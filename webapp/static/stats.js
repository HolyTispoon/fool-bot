/*
 * Every web game's numbers, cut by kind (GET /api/stats). The tables
 * are d12ball/stats.py's, the ones /d12ball stats posts, set here as
 * text; which kinds there are, and what each is called, is the
 * server's too.
 */

const kind = document.getElementById("kind");

function table(lines) {
  const pre = document.createElement("pre");
  pre.className = "stats-table";
  pre.textContent = lines.join("\n");
  return pre;
}

async function load() {
  const query = new URLSearchParams({ kind: kind.value || "all", source: "web" });
  try {
    const response = await fetch(`/api/stats?${query}`);
    if (!response.ok) return;
    const report = await response.json();
    if (!kind.options.length) {
      for (const one of report.kinds) {
        const option = document.createElement("option");
        option.value = one.value;
        option.textContent = one.label[0].toUpperCase() + one.label.slice(1);
        kind.append(option);
      }
      kind.value = report.kind;
    }
    document.getElementById("heading").replaceChildren(table(report.heading));
    document.getElementById("reports").replaceChildren(
      ...report.reports.flatMap((one) => one.tables.map(table)),
    );
    document.getElementById("nothing").hidden = report.reports.length > 0;
  } catch (failure) {
    /* A page of numbers; reloading it asks again. */
  }
}

kind.addEventListener("change", load);
load();
