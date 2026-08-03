if (window.htmx) {
  htmx.config.defaultSwapStyle = "innerHTML";
}

function wirePriceClick() {
  var wrap = document.getElementById("pt-price-wrap");
  if (!wrap) return;
  var gd = wrap.querySelector(".plotly-graph-div");
  if (!gd || gd._ptWired || !gd.on) return;
  gd._ptWired = true;
  gd.on("plotly_click", function (e) {
    var p = e.points && e.points[0];
    if (!p || p.customdata == null) return;
    var params = new URLSearchParams(window.location.search);
    var run = params.get("run") || "";
    var strat = params.get("strat") || "";
    window.location.href =
      "/decisions?run=" +
      encodeURIComponent(run) +
      "&strat=" +
      encodeURIComponent(strat) +
      "&ddate=" +
      encodeURIComponent(p.customdata);
  });
}

document.addEventListener("DOMContentLoaded", wirePriceClick);
document.body.addEventListener("htmx:afterSwap", wirePriceClick);
