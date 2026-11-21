import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The list view: search row, folder chips and the scrolling login cards.
Item {
  id: list
  required property var panel

  anchors.fill: parent

  property alias searchField: searchField
  property alias listArea: listArea
  property alias listColumn: listColumn
  readonly property real chromeHeight: topChrome.implicitHeight
  readonly property real listContentHeight: listColumn.implicitHeight

  function ensureVisible(item) {
    var top = item.mapToItem(listColumn, 0, 0).y
    var bottom = top + item.height
    if (top < listFlick.contentY)
      listFlick.contentY = Math.max(0, top)
    else if (bottom > listFlick.contentY + listFlick.height)
      listFlick.contentY = Math.min(listFlick.contentHeight - listFlick.height, bottom - listFlick.height)
  }

  // Arrow keys from the key catcher, by section.
  function move(dx, dy) {
    if (panel.focusSection === "folders") {
      if (dx !== 0)
        panel.folderIndex = Math.max(0, Math.min(panel.folderChipIds.length - 1, panel.folderIndex + dx))
      else if (dy > 0) {
        if (panel.visibleRecords.length > 0)
          panel.setListCursor(panel.listIndex)
        else
          panel.focusSection = "search"
      }
      return
    }
    if (panel.focusSection === "search") {
      if (dy > 0 && panel.visibleRecords.length > 0)
        panel.selectRow(1)
      else if (dy < 0 && panel.folderChipIds.length > 1)
        panel.focusSection = "folders"
      return
    }
    if (panel.focusSection === "list") {
      if (dx > 0) {
        panel.openSelectedOverflow()
        return
      }
      if (dy !== 0)
        panel.selectRow(dy)
    }
  }

  // Single-letter keys from the key catcher.
  function handleTextKey(t) {
    if (t === "/")
      searchField.forceActiveFocus()
    else if (t === "m" || t === "M")
      panel.openSelectedOverflow()
    else if (t === "u" || t === "U")
      panel.copyAccountSelected()
    else if ((t === "x" || t === "X") && panel.focusSection === "list")
      panel.confirmCard.removeRecord(panel.currentRecord())
  }

  Column {
    id: topChrome
    width: parent.width
    spacing: Style.space(8)

    RowLayout {
      width: parent.width
      spacing: Style.space(6)
      visible: list.panel.view === "list"

      FormField {
        id: searchField
        panel: list.panel
        Layout.fillWidth: true
        placeholderText: "Search"
        leftPadding: horizontalPadding + Style.space(22)

        Text {
          anchors.left: parent.left
          anchors.leftMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          text: "󰍉"
          color: list.panel.dim
          font.family: list.panel.contentFontFamily
          font.pixelSize: Style.font.body
        }

        text: list.panel.searchText
        font.family: list.panel.contentFontFamily
        foreground: list.panel.foreground
        font.pixelSize: Style.font.body
        verticalPadding: Style.space(4)
        hasCursor: list.panel.focusSection === "search" && !activeFocus
        onTextChanged: list.panel.searchText = text
        onActiveFocusChanged: if (activeFocus) list.panel.focusSection = "search"

        // A pointer at rest over the field must not take the cursor.
        readonly property bool pointerOver: searchHover.hovered
        PointerTracker { id: searchHover; panel: list.panel }
        Connections {
          target: list.panel
          function onPointerMoved() {
            if (searchHover.hovered) list.panel.focusSection = "search"
          }
        }
        Keys.onPressed: function(event) {
          if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_N) {
            list.panel.openAddView()
            event.accepted = true
          } else if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_U) {
            list.panel.copyAccountSelected()
            event.accepted = true
          } else if (event.key === Qt.Key_Escape) {
            list.panel.handleEscape()
            event.accepted = true
          } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            list.panel.handleEnter(event)
            event.accepted = true
          } else if (event.key === Qt.Key_Down) {
            if (list.panel.visibleRecords.length > 0) {
              list.panel.selectRow(1)
              list.panel.focusSection = "list"
              list.panel.focusCatcher()
            }
            event.accepted = true
          } else if (event.key === Qt.Key_Up) {
            if (list.panel.folderChipIds.length > 1) {
              list.panel.focusSection = "folders"
              list.panel.focusCatcher()
            } else if (list.panel.visibleRecords.length > 0) {
              list.panel.selectRow(-1)
              list.panel.focusCatcher()
            }
            event.accepted = true
          }
        }
      }

      PanelActionButton {
        iconText: "󰐕"
        tooltipText: "Add login"
        foreground: list.panel.foreground
        fontFamily: list.panel.contentFontFamily
        size: searchField.height
        bordered: true
        color: _hot ? Style.hoverFillFor(foreground, foreground)
          : Qt.rgba(list.panel.foreground.r, list.panel.foreground.g, list.panel.foreground.b, 0.10)
        onClicked: list.panel.openAddView()
      }

      PanelActionButton {
        size: searchField.height
        bordered: true
        iconText: list.panel.centerPanel ? "󰉣" : "󰉠"
        tooltipText: list.panel.centerPanel ? "Open under the icon (Ctrl+P)" : "Open centered on the bar (Ctrl+P)"
        foreground: list.panel.foreground
        fontFamily: list.panel.contentFontFamily
        onClicked: list.panel.togglePanelPosition()
      }
    }

    Flickable {
      id: folderFlick
      visible: list.panel.view === "list" && list.panel.loadedRecordCount > 0
      width: parent.width
      height: folderRow.implicitHeight
      contentWidth: folderRow.implicitWidth
      contentHeight: folderRow.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.HorizontalFlick

      function clampX(x) {
        return Math.max(0, Math.min(x, Math.max(0, contentWidth - width)))
      }

      function ensureChipVisible(idx) {
        var chip = chipRepeater.itemAt(idx)
        if (!chip) return
        if (chip.x < contentX)
          contentX = clampX(chip.x)
        else if (chip.x + chip.width > contentX + width)
          contentX = clampX(chip.x + chip.width - width)
      }

      Connections {
        target: list.panel
        function onFolderIndexChanged() { folderFlick.ensureChipVisible(list.panel.folderIndex) }
      }

      // The wheel scrolls the chips sideways while the cursor is over them.
      WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
          if (folderFlick.contentWidth <= folderFlick.width)
            return
          var delta = event.angleDelta.x !== 0 ? event.angleDelta.x : event.angleDelta.y
          folderFlick.contentX = folderFlick.clampX(folderFlick.contentX - delta)
          event.accepted = true
        }
      }

      Row {
        id: folderRow
        spacing: Style.space(6)

        Repeater {
          id: chipRepeater
          model: list.panel.folderChipIds

          Pill {
            panel: list.panel
            required property var modelData
            required property int index
            label: modelData.name
            active: list.panel.folderFilter === modelData.id
            hasCursor: list.panel.focusSection === "folders" && list.panel.folderIndex === index
            onClicked: list.panel.setFolderFilter(modelData.id)
            onHovered: {
              list.panel.focusSection = "folders"
              list.panel.folderIndex = index
            }
          }
        }
      }
    }
  }

  Item {
    id: listArea
    anchors.top: topChrome.bottom
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.topMargin: Style.space(8)
    anchors.bottomMargin: list.panel.footerReserve
    visible: list.panel.view === "list"

    Item {
      id: emptyState
      anchors.fill: parent
      visible: list.panel.visibleRecords.length === 0

      Column {
        anchors.centerIn: parent
        width: parent.width
        spacing: Style.space(4)

        Text {
          width: parent.width
          text: list.panel.listError !== "" ? list.panel.listError
            : list.panel.listLoading ? "Loading\u2026"
            : list.panel.loadedRecordCount === 0 ? "No logins yet" : "No matches"
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          color: list.panel.dim
          font.family: list.panel.contentFontFamily
          font.pixelSize: Style.font.body
          horizontalAlignment: Text.AlignHCenter
        }

        SolidButton {
          panel: list.panel
          anchors.horizontalCenter: parent.horizontalCenter
          visible: list.panel.listError === "" && !list.panel.listLoading
          label: "+ Add login"
          onClicked: list.panel.openAddView()
        }

        Text {
          width: parent.width
          visible: list.panel.listError === "" && !list.panel.listLoading
          text: "Enter or Ctrl+N to add"
          color: list.panel.dim
          font.family: list.panel.contentFontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
        }
      }
    }

    Flickable {
      id: listFlick
      anchors.fill: parent
      visible: list.panel.visibleRecords.length > 0
      contentWidth: width
      contentHeight: listColumn.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      interactive: contentHeight > height
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

      WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
          if (listFlick.contentHeight <= listFlick.height)
            return
          var maxY = listFlick.contentHeight - listFlick.height
          listFlick.contentY = Math.max(0, Math.min(listFlick.contentY - event.angleDelta.y, maxY))
          event.accepted = true
        }
      }

      Column {
        id: listColumn
        width: listFlick.width
        spacing: Style.space(10)

        Repeater {
          model: list.panel.folderFilter === Model.ALL_FOLDERS ? list.panel.groups : []

          FolderCard {
            panel: list.panel
            listView: list
            required property var modelData
            width: listColumn.width
            title: modelData.name
            records: modelData.records
          }
        }

        FolderCard {
          panel: list.panel
          listView: list
          visible: list.panel.folderFilter !== Model.ALL_FOLDERS
          // The selected chip already names the folder.
          showHeader: false
          topPadding: Style.space(4)
          width: listColumn.width
          title: list.panel.folderFilter
          records: list.panel.folderFilter !== Model.ALL_FOLDERS ? list.panel.filteredRecords : []
        }
      }
    }
  }
}
