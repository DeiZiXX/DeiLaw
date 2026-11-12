; DeiLaw GPL/SignPath candidate - open-source NSIS installer (zlib only).
; No external NSIS plugins. License and privacy disclosure are shown before install.
Unicode true
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"

!ifndef APP_VERSION
  !define APP_VERSION "0.3.1"
!endif
!ifndef DEILAW_SOURCE
  !define DEILAW_SOURCE "..\dist\DeiLaw"
!endif
!ifndef DEILAW_OUTPUT
  !define DEILAW_OUTPUT "..\release"
!endif

Name "DeiLaw ${APP_VERSION}"
OutFile "${DEILAW_OUTPUT}\DeiLaw_Setup_v${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\Programs\DeiLaw"
InstallDirRegKey HKCU "Software\DeiLaw" "InstallDir"
RequestExecutionLevel user
SetCompressor zlib
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "DeiLaw"
VIAddVersionKey /LANG=1033 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "FileDescription" "DeiLaw Windows Installer"
VIAddVersionKey /LANG=1033 "CompanyName" "DeiZi"

!define MUI_ICON "${__FILEDIR__}\assets\deilaw_installer.ico"
!define MUI_UNICON "${__FILEDIR__}\assets\deilaw_installer.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\DeiLaw.exe"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${__FILEDIR__}\..\LICENSE"
; SignPath requires displaying privacy policy during installation.
!insertmacro MUI_PAGE_LICENSE "${__FILEDIR__}\PRIVACY_INSTALL.txt"
Page custom PrivacyPageCreate PrivacyPageLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"
!insertmacro MUI_LANGUAGE "English"

Var Dialog
Var CheckUpdates
Var CheckLaws
Var CheckReplies
Var OptUpdates
Var OptLaws
Var OptReplies

Function .onInit
  ; Default-deny: no background network traffic without user choice.
  StrCpy $OptUpdates "false"
  StrCpy $OptLaws "false"
  StrCpy $OptReplies "false"
  ; The older Inno Setup uninstaller has different upgrade rules.
  ; Refuse unattended overwrite instead of breaking existing user installs.
  IfFileExists "$INSTDIR\unins000.exe" 0 init_done
    IfSilent 0 +2
      Abort
    MessageBox MB_ICONSTOP|MB_OK "Обнаружена старая установка DeiLaw (Inno Setup). Сохраните папку data и удалите старую версию через Windows перед установкой новой."
    Abort
  init_done:
FunctionEnd

Function PrivacyPageCreate
  !insertmacro MUI_HEADER_TEXT "Сетевые функции" "Выберите необязательные фоновые подключения"
  nsDialogs::Create 1018
  Pop $Dialog
  ${If} $Dialog == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 33u "Отправка запросов в интернет по вашему действию (вход, поиск законов, Cloud AI) описана в политике конфиденциальности. Следующие фоновые запросы по умолчанию отключены."
  Pop $0
  ${NSD_CreateCheckbox} 0 38u 100% 14u "Проверять обновления DeiLaw через GitHub автоматически"
  Pop $CheckUpdates
  ${NSD_CreateCheckbox} 0 60u 100% 14u "Автоматически синхронизировать законы RMRP"
  Pop $CheckLaws
  ${NSD_CreateCheckbox} 0 82u 100% 28u "Получать уведомления об ответах разработчика (Supabase, запросы в фоне)"
  Pop $CheckReplies
  nsDialogs::Show
FunctionEnd

Function PrivacyPageLeave
  ${NSD_GetState} $CheckUpdates $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $OptUpdates "true"
  ${Else}
    StrCpy $OptUpdates "false"
  ${EndIf}
  ${NSD_GetState} $CheckLaws $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $OptLaws "true"
  ${Else}
    StrCpy $OptLaws "false"
  ${EndIf}
  ${NSD_GetState} $CheckReplies $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $OptReplies "true"
  ${Else}
    StrCpy $OptReplies "false"
  ${EndIf}
FunctionEnd

Section "DeiLaw" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${DEILAW_SOURCE}\*.*"
  File /oname=PRIVACY.md "${__FILEDIR__}\..\PRIVACY.md"
  File /oname=LICENSE.txt "${__FILEDIR__}\..\LICENSE"
  File /oname=THIRD_PARTY_NOTICES.md "${__FILEDIR__}\..\THIRD_PARTY_NOTICES.md"
  ; Avoid overwriting preferences and personal data when updating.
  CreateDirectory "$INSTDIR\data"
  IfFileExists "$INSTDIR\data\settings.json" settings_done
    FileOpen $0 "$INSTDIR\data\settings.json" w
    FileWrite $0 '{"auto_check_program_updates": $OptUpdates, "auto_update_laws_on_startup": $OptLaws, "background_reply_notifications": $OptReplies}'
    FileClose $0
  settings_done:
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\DeiLaw" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw" "DisplayName" "DeiLaw ${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw" "Publisher" "DeiZi"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw" "NoRepair" 1
  CreateDirectory "$SMPROGRAMS\DeiLaw"
  CreateShortCut "$SMPROGRAMS\DeiLaw\DeiLaw.lnk" "$INSTDIR\DeiLaw.exe"
  CreateShortCut "$SMPROGRAMS\DeiLaw\Удалить DeiLaw.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\DeiLaw\DeiLaw.lnk"
  Delete "$SMPROGRAMS\DeiLaw\Удалить DeiLaw.lnk"
  RMDir "$SMPROGRAMS\DeiLaw"
  Delete "$DESKTOP\DeiLaw.lnk"
  Delete "$INSTDIR\DeiLaw.exe"
  Delete "$INSTDIR\PRIVACY.md"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\assets"
  Delete "$INSTDIR\Uninstall.exe"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\DeiLaw"
  DeleteRegKey HKCU "Software\DeiLaw"
  ; Preserve data/ and all user-owned files for safe manual recovery.
  RMDir "$INSTDIR"
SectionEnd
