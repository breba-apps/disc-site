const win = window;
const doc = window.document;

console.log(doc)

// Notify parent (generator.html) of the current page path on every load
window.parent.postMessage({
    method: "preview_page_changed",
    body: window.location.pathname.replace(/^\//, '')
}, "*");

doc.addEventListener('mouseup', () => {
    const sel = win.getSelection().toString().trim();
    if (!sel) return;


    // get the bounding rect of the selection
    const range = win.getSelection().getRangeAt(0);
    const r = range.getBoundingClientRect();

    // ideal absolute coords
    const absLeft = r.left;
    const absTop = r.bottom + 5;


    window.parent.postMessage({method: "preview_mouseup", selection: sel, left: absLeft, top: absTop}, "*")

});

doc.addEventListener('mousedown', () => {
    window.parent.postMessage({method: "preview_mousedown"}, "*")
});
