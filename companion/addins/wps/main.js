/* Official WPS JS add-in entry points, loaded by the WPS add-in engine. */
var kotoPane = null;
var kotoBuild = '20261025.1';
function OnKotoLoad(ribbon) { return true; }
function OpenKoto(control) {
  // Reuse the pane so hiding/reopening never loses the conversation or draft.
  if (kotoPane) {
    try { kotoPane.Visible = true; return true; } catch (_) { kotoPane = null; }
  }
  kotoPane = wps.CreateTaskPane(location.origin + '/ui/?host=wps&build=' + kotoBuild, 'Koto');
  if (!kotoPane) throw new Error('无法创建 Koto 任务窗格');
  kotoPane.Visible = true;
  try { kotoPane.Width = 380; } catch (_) {}
  return true;
}
function ToggleKoto(control) {
  // Keep the earlier callback compatible with already loaded ribbons.
  return OpenKoto(control);
}
function RefreshKoto(control) {
  if (!kotoPane) return OpenKoto(control);
  kotoPane.Navigate(location.origin + '/ui/?host=wps&build=' + kotoBuild);
  kotoPane.Visible = true;
  return true;
}
