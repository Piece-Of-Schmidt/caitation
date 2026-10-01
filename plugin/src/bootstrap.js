/* global Services, Zotero */
/* eslint-disable no-unused-vars */

// Zotero plugin lifecycle hooks. All logic lives in caitation.js.

var Caitation;

function install() {}

async function startup({ id, version, rootURI }) {
  Services.scriptloader.loadSubScript(rootURI + "caitation.js");
  Caitation.init({ id, version, rootURI });
  Caitation.register();
  for (const window of Zotero.getMainWindows()) {
    Caitation.addToWindow(window);
  }
}

function onMainWindowLoad({ window }) {
  Caitation.addToWindow(window);
}

function onMainWindowUnload({ window }) {
  Caitation.removeFromWindow(window);
}

function shutdown() {
  if (!Caitation) return;
  for (const window of Zotero.getMainWindows()) {
    Caitation.removeFromWindow(window);
  }
  Caitation.unregister();
  Caitation = undefined;
}

function uninstall() {}
