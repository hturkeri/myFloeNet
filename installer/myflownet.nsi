; myFlowNet - per-user installer (no administrator rights)
; Built by build_installer.py:  makensis -DVERSION=x -DSTAGE=dir -DOUTFILE=file -DSIZE_KB=n myflownet.nsi

Target amd64-unicode          ; 64-bit installer (the bundled Python is 64-bit)
ManifestDPIAware true
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!define APP "myFlowNet"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

Name "${APP} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "Software\${APP}\Install" "Path"
BrandingText "${APP} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APP} - 1D flow network solver (per-user setup)"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "See THIRD_PARTY_NOTICES.txt"

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON "${STAGE}\myflownet.ico"
!define MUI_UNICON "${STAGE}\myflownet.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\python\pythonw.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "-m myflownet"
!define MUI_FINISHPAGE_RUN_TEXT "$(RunNow)"
!define MUI_LICENSEPAGE_BUTTON "$(^NextBtn)"
!define MUI_LICENSEPAGE_TEXT_BOTTOM "$(NoticeBottom)"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${STAGE}\THIRD_PARTY_NOTICES.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Turkish"
!insertmacro MUI_LANGUAGE "English"

LangString RunNow ${LANG_TURKISH} "myFlowNet'i şimdi başlat"
LangString RunNow ${LANG_ENGLISH} "Start myFlowNet now"
LangString NoticeBottom ${LANG_TURKISH} "Bu bileşenlerin lisans metinleri kurulum klasöründeki 'licenses' klasöründedir."
LangString NoticeBottom ${LANG_ENGLISH} "The licence texts of these components are installed in the 'licenses' folder."
LangString SecMain ${LANG_TURKISH} "myFlowNet (gerekli)"
LangString SecMain ${LANG_ENGLISH} "myFlowNet (required)"
LangString SecDesk ${LANG_TURKISH} "Masaüstü kısayolu"
LangString SecDesk ${LANG_ENGLISH} "Desktop shortcut"
LangString SecExamples ${LANG_TURKISH} "Örnek modeller kısayolu"
LangString SecExamples ${LANG_ENGLISH} "Shortcut to the example models"
LangString Running ${LANG_TURKISH} "myFlowNet açık görünüyor. Kapatıp Tamam'a basın."
LangString Running ${LANG_ENGLISH} "myFlowNet seems to be running. Close it and press OK."

Section "$(SecMain)" SEC_MAIN
  SectionIn RO
  SetShellVarContext current
  ; replace an earlier installation cleanly (keeps nothing of the old runtime)
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\licenses"
  SetOutPath "$INSTDIR"
  File /r "${STAGE}\*.*"
  ; precompile so that the first start is fast (errors are harmless)
  nsExec::Exec '"$INSTDIR\python\python.exe" -X utf8 -m compileall -q "$INSTDIR\app\myflownet"'
  Pop $0

  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-m myflownet" \
                 "$INSTDIR\myflownet.ico" 0 SW_SHOWNORMAL "" "1D flow network solver"
  CreateShortcut "$SMPROGRAMS\${APP}\Theory guide.lnk" "$INSTDIR\app\docs\THEORY.md"
  CreateShortcut "$SMPROGRAMS\${APP}\Uninstall ${APP}.lnk" "$INSTDIR\Uninstall.exe"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\${APP}\Install" "Path" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP} ${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${APP}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\myflownet.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" ${SIZE_KB}
SectionEnd

Section "$(SecDesk)" SEC_DESK
  SetShellVarContext current
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\python\pythonw.exe" "-m myflownet" \
                 "$INSTDIR\myflownet.ico" 0 SW_SHOWNORMAL "" "1D flow network solver"
SectionEnd

Section "$(SecExamples)" SEC_EX
  SetShellVarContext current
  CreateShortcut "$SMPROGRAMS\${APP}\Examples.lnk" "$INSTDIR\app\examples"
SectionEnd

Function .onInit
  SetShellVarContext current      ; shortcuts and registry entries for the current user only
FunctionEnd

Function .onVerifyInstDir
  ; must be writable without administrator rights
  ClearErrors
  CreateDirectory "$INSTDIR"
  IfErrors 0 +2
    Abort
FunctionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\licenses"
  Delete "$INSTDIR\myflownet.ico"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP}\Install"
SectionEnd
