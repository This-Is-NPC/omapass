import QtQuick

// Tells real pointer motion from hover that Qt re-delivers when items move
// under a pointer at rest. The first position after open() is only a
// baseline. The confirm dialog hosts its own tracker: it sits above the
// key catcher, which then gets no hover.
HoverHandler {
  id: tracker
  required property var panel

  onPointChanged: {
    var p = point.scenePosition
    var last = tracker.panel.lastPointer
    if (last && last.x === p.x && last.y === p.y)
      return
    tracker.panel.lastPointer = p
    if (last)
      Qt.callLater(tracker.panel.pointerMoved)
  }
}
