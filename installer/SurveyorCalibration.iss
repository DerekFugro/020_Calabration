; Inno Setup script - Setup.exe for the van PCs.  Built by installer\build.ps1
; (which passes /DAppVersion=2026.11.06-abc1234 /DAppNumber=2026.11.06).
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#ifndef AppNumber
  #define AppNumber "0.0.0"
#endif
#define Dist "dist\SurveyorCalibration"

[Setup]
; never change AppId - it is how Windows knows a new Setup.exe is an update
AppId={{6F1B7C2E-4D0A-4E8B-9C35-020CA1AB2026}
AppName=SurveyorCalibration
AppVerName=SurveyorCalibration {#AppVersion}
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumber}
AppPublisher=Fugro
DefaultDirName={autopf}\SurveyorCalibration
DefaultGroupName=SurveyorCalibration
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=SurveyorCalibration_Setup_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\SurveyorCalibration.exe
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut"; Flags: unchecked

[InstallDelete]
; an update replaces the program files completely (old libraries never linger)
Type: filesandordirs; Name: "{app}\_internal"

[Dirs]
; boards and Old School sites: one shared copy, every user may add and edit
Name: "{commonappdata}\SurveyorCalibration"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\SurveyorCalibration\Cal_board"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{commonappdata}\SurveyorCalibration\control"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "{#Dist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; shipped boards and sites - added if missing, never overwritten, kept on uninstall
Source: "{#Dist}\_internal\Cal_board\*"; DestDir: "{commonappdata}\SurveyorCalibration\Cal_board"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs
Source: "{#Dist}\_internal\control\*"; DestDir: "{commonappdata}\SurveyorCalibration\control"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\SurveyorCalibration"; Filename: "{app}\SurveyorCalibration.exe"
Name: "{autoprograms}\SurveyorCapture"; Filename: "{app}\SurveyorCapture.exe"
Name: "{autodesktop}\SurveyorCalibration"; Filename: "{app}\SurveyorCalibration.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SurveyorCalibration.exe"; Description: "Start SurveyorCalibration"; Flags: nowait postinstall skipifsilent
