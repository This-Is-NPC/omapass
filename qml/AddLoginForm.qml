import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui

// The Account/Nostr form and the password generator. The form's values live
// on the panel (addFolder, addAccount, addPassword, ...); this file owns the
// fields and the save and generate flows.
Column {
  id: form
  required property var panel

  property alias folderField: folderField
  property alias accountField: accountField
  property alias passwordField: passwordField

  function clearPasswordField() {
    passwordField.text = ""
  }

  // Focus the first field that still needs input.
  function focusFirstEmpty() {
    folderField.forceActiveFocus()
    if (panel.addFolder !== "" && panel.addAccount === "") accountField.forceActiveFocus()
    else if (panel.addFolder !== "" && panel.addAccount !== "") passwordField.forceActiveFocus()
  }

  function generate() {
    if (panel.addKind === "nostr") generateNostrKey()
    else generateAddPassword()
  }

  // Ctrl+G generates, Ctrl+E reveals the password (account kind, where
  // allowed) and Ctrl+1/Ctrl+2 pick the kind. True when the key was taken.
  function handleCtrlKey(event, allowReveal) {
    if (!(event.modifiers & Qt.ControlModifier))
      return false
    if (event.key === Qt.Key_G)
      generate()
    else if (event.key === Qt.Key_E && allowReveal && panel.addKind === "account")
      panel.addPasswordVisible = !panel.addPasswordVisible
    else if (event.key === Qt.Key_1)
      panel.addKind = "account"
    else if (event.key === Qt.Key_2)
      panel.addKind = "nostr"
    else
      return false
    return true
  }

  // Enter from the key catcher.
  function activate() {
    if (panel.focusSection === "addKind")
      folderField.forceActiveFocus()
    else if (passwordField.activeFocus)
      panel.saveAdd()
    else if (accountField.activeFocus && panel.addKind === "nostr")
      generateNostrKey()
  }

  function cancelAdd() {
    panel.wipeSensitiveState()
    panel.addFolder = ""
    panel.addAccount = ""
    panel.addError = ""
    panel.addKind = "account"
    panel.view = "list"
    panel.focusSearchSoon()
  }

  function saveAdd(replace) {
    panel.addError = ""
    var secret = panel.addPassword
    var account = panel.addAccount
    var folder = panel.addFolder
    var token = ++panel.formToken
    panel.addPassword = ""
    passwordField.text = ""
    panel.vault.store(account, folder, secret, function(ok, err, code) {
      // Ignore a reply for a form that was closed, wiped or edited since.
      // The field was emptied above; any text there now is a new edit.
      var current = token === panel.formToken && panel.opened && panel.view === "add"
        && panel.addKind === "account" && panel.addAccount === account
        && panel.addFolder === folder && panel.addPassword === ""
      // A failed save keeps the password in the form, so it can be retried.
      if (!ok && current) {
        panel.addPassword = secret
        passwordField.text = secret
      }
      secret = ""
      if (!ok && panel.confirmCard.reportDamaged(err, code))
        return
      if (!current) {
        if (ok) panel.vault.refresh()
        return
      }
      if (!ok && code === panel.vault.exitExists) {
        panel.confirmCard.askReplace("replaceAccount", String(account || "").trim(), String(folder || "").trim())
        return
      }
      if (ok) {
        panel.addFolder = ""
        panel.addAccount = ""
        panel.addError = ""
        panel.view = "list"
        panel.flashSaved()
        panel.focusSearchSoon()
      } else {
        panel.addError = err
      }
    }, "", replace === true)
  }

  function generateAddPassword() {
    var token = panel.formToken
    panel.vault.generatePassword(function(pw) {
      if (token !== panel.formToken || !panel.opened || panel.view !== "add")
        return
      if (!pw) {
        panel.addError = "Could not generate password"
        return
      }
      // A generated password always starts masked, even if the field was
      // revealed before.
      panel.addPasswordVisible = false
      panel.addPassword = pw
      panel.addPasswordGenerated = true
      passwordField.text = pw
      panel.flashCopied("Generated password")
    })
  }

  function doGenerateNostr(replace) {
    var nick = String(panel.addAccount || "").trim()
    var fold = String(panel.addFolder || "").trim() || "Nostr"
    var account = panel.addAccount
    var folder = panel.addFolder
    var token = ++panel.formToken
    panel.vault.generateNostr(nick, fold, function(ok, msg, code) {
      if (!ok && panel.confirmCard.reportDamaged(msg, code))
        return
      // Ignore a reply for a form that was closed, wiped or edited since.
      var current = token === panel.formToken && panel.opened && panel.view === "add"
        && panel.addKind === "nostr" && panel.addAccount === account && panel.addFolder === folder
      if (!current) {
        if (ok) panel.vault.refresh()
        return
      }
      if (!ok && code === panel.vault.exitExists) {
        panel.confirmCard.askReplace("replaceNostr", nick, fold)
        return
      }
      if (ok) {
        panel.addPassword = ""
        panel.addFolder = ""
        panel.addAccount = ""
        panel.addError = ""
        panel.view = "list"
        panel.vault.refresh()
        panel.flashSaved()
        panel.focusSearchSoon()
      } else {
        panel.addError = msg || "Failed to generate Nostr key"
      }
    }, replace === true)
  }

  function generateNostrKey() {
    panel.addError = ""
    var nick = String(panel.addAccount || "").trim()
    if (!nick) {
      panel.addError = "Need a nickname in Account"
      return
    }
    doGenerateNostr(false)
  }

  width: parent.width
  spacing: Style.space(8)
  visible: form.panel.view === "add"

  Text {
    text: form.panel.addKind === "nostr" ? "New Nostr key" : "New login"
    color: form.panel.foreground
    font.family: form.panel.contentFontFamily
    font.pixelSize: Style.font.body
    font.bold: true
  }

  BorderSurface {
    id: addKindRow
    width: parent.width
    height: kindRow.implicitHeight + contentTopInset + contentBottomInset
    color: "transparent"
    borderSpec: Border.flat(form.panel.subtleBorder, 1)
    radius: Style.cornerRadius
    padding: Style.space(3)

    RowLayout {
      id: kindRow
      x: addKindRow.contentLeftInset
      y: addKindRow.contentTopInset
      width: addKindRow.width - addKindRow.contentLeftInset - addKindRow.contentRightInset
      spacing: Style.space(3)

      Pill {

        panel: form.panel
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        label: "Account"
        borderless: true
        hoverFollows: form.panel.focusSection !== "addKind"
        active: form.panel.addKind === "account"
        hasCursor: form.panel.focusSection === "addKind" && form.panel.addKind === "account"
        onClicked: form.panel.addKind = "account"
      }

      Pill {

        panel: form.panel
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        label: "Nostr"
        borderless: true
        hoverFollows: form.panel.focusSection !== "addKind"
        active: form.panel.addKind === "nostr"
        hasCursor: form.panel.focusSection === "addKind" && form.panel.addKind === "nostr"
        onClicked: form.panel.addKind = "nostr"
      }
    }
  }

  Text {
    text: "Folder"
    color: form.panel.dim
    font.family: form.panel.contentFontFamily
    font.pixelSize: Style.font.caption
  }

  FormField {

    panel: form.panel
    id: folderField
    width: parent.width
    placeholderText: form.panel.addKind === "nostr" ? "Nostr (default)" : "Folder"
    text: form.panel.addFolder
    foreground: form.panel.foreground
    onTextChanged: form.panel.addFolder = text
    onActiveFocusChanged: if (activeFocus) form.panel.focusSection = "addFields"
    Keys.onPressed: function(event) {
      if (form.handleCtrlKey(event, false)) {
        event.accepted = true
      } else if (event.key === Qt.Key_Tab) {
        if (event.modifiers & Qt.ShiftModifier) {
          form.panel.focusSection = "addKind"
          form.panel.focusCatcher()
        } else {
          accountField.forceActiveFocus()
        }
        event.accepted = true
      } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
        accountField.forceActiveFocus()
        event.accepted = true
      } else if (event.key === Qt.Key_Escape) {
        form.cancelAdd()
        event.accepted = true
      }
    }
  }

  Text {
    text: form.panel.addKind === "nostr" ? "Nickname" : "Account or nickname"
    color: form.panel.dim
    font.family: form.panel.contentFontFamily
    font.pixelSize: Style.font.caption
  }

  FormField {

    panel: form.panel
    id: accountField
    width: parent.width
    placeholderText: form.panel.addKind === "nostr" ? "Nickname" : "Account or nickname"
    text: form.panel.addAccount
    font.family: form.panel.contentFontFamily
    onTextChanged: form.panel.addAccount = text
    onActiveFocusChanged: if (activeFocus) form.panel.focusSection = "addFields"
    Keys.onPressed: function(event) {
      if (form.handleCtrlKey(event, false)) {
        event.accepted = true
      } else if (event.key === Qt.Key_Tab) {
        if (event.modifiers & Qt.ShiftModifier)
          folderField.forceActiveFocus()
        else if (form.panel.addKind === "account")
          passwordField.forceActiveFocus()
        event.accepted = true
      } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
        if (form.panel.addKind === "nostr")
          form.generateNostrKey()
        else
          passwordField.forceActiveFocus()
        event.accepted = true
      } else if (event.key === Qt.Key_Escape) {
        form.cancelAdd()
        event.accepted = true
      }
    }
  }

  RowLayout {
    width: parent.width
    visible: form.panel.addKind === "account"

    Text {
      Layout.fillWidth: true
      text: "Password"
      color: form.panel.dim
      font.family: form.panel.contentFontFamily
      font.pixelSize: Style.font.caption
    }

    // Only the length: the password stays masked until revealed.
    Text {
      visible: form.panel.addPasswordGenerated && form.panel.addPassword.length > 0
      textFormat: Text.PlainText
      text: "󰄬 Generated · " + form.panel.addPassword.length + " chars"
      color: form.panel.accentColor
      font.family: form.panel.contentFontFamily
      font.pixelSize: Style.font.caption
    }
  }

  RowLayout {
    width: parent.width
    spacing: Style.space(6)
    visible: form.panel.addKind === "account"

    FormField {

      panel: form.panel
      id: passwordField
      Layout.fillWidth: true
      placeholderText: "Password"
      password: !form.panel.addPasswordVisible
      text: form.panel.addPassword
      font.family: form.panel.contentFontFamily
      onTextChanged: form.panel.addPassword = text
      onTextEdited: form.panel.addPasswordGenerated = false
      onActiveFocusChanged: if (activeFocus) form.panel.focusSection = "addFields"
      Keys.onPressed: function(event) {
        if (form.handleCtrlKey(event, true)) {
          event.accepted = true
        } else if (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier)) {
          accountField.forceActiveFocus()
          event.accepted = true
        } else if (event.key === Qt.Key_Escape) {
          form.cancelAdd()
          event.accepted = true
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          form.saveAdd()
          event.accepted = true
        }
      }
    }

    PanelActionButton {
      iconText: form.panel.addPasswordVisible ? "󰈉" : "󰈈"
      tooltipText: form.panel.addPasswordVisible ? "Hide password" : "Show password"
      foreground: form.panel.foreground
      fontFamily: form.panel.contentFontFamily
      onClicked: form.panel.addPasswordVisible = !form.panel.addPasswordVisible
    }

    PanelActionButton {
      iconText: "󰑐"
      tooltipText: "Generate password"
      foreground: form.panel.foreground
      fontFamily: form.panel.contentFontFamily
      onClicked: form.generateAddPassword()
    }
  }

  RowLayout {
    width: parent.width
    spacing: Style.space(8)

    SolidButton {

      panel: form.panel
      Layout.fillWidth: true
      Layout.preferredWidth: 1
      label: "Cancel"
      onClicked: form.cancelAdd()
    }

    SolidButton {

      panel: form.panel
      Layout.fillWidth: true
      Layout.preferredWidth: 1
      label: form.panel.addKind === "nostr" ? "Generate key" : "Save"
      primary: true
      muted: !form.panel.canSubmitAdd
      onClicked: form.panel.addKind === "nostr" ? form.generateNostrKey() : form.saveAdd()
    }
  }

  Text {
    width: parent.width
    visible: form.panel.addError !== ""
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    text: form.panel.addError
    color: form.panel.urgentColor
    font.family: form.panel.contentFontFamily
    font.pixelSize: Style.font.caption
  }
}
