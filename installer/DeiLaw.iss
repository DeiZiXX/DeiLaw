#define MyAppName "DeiLaw"
#ifndef MyAppVersion
#define MyAppVersion "0.2.1a"
#endif
#define MyAppPublisher "DeiZi"
#define MyAppExeName "DeiLaw.exe"
#define MyAppDescription "RMRP Law Assistant"
#ifndef MyOutputDir
#define MyOutputDir "..\release"
#endif

[Setup]
AppId={{8E7CB736-0DD8-4CD0-9971-385BF1234B61}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppComments={#MyAppDescription}
DefaultDirName={localappdata}\Programs\DeiLaw
DefaultGroupName=DeiLaw
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#MyOutputDir}
OutputBaseFilename=DeiLaw_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayName=DeiLaw
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\deilaw_installer.ico

; Стиль DeiLaw: тёмная тема + фирменный синий акцент.
; WizardBackImageFile/WizardBackColor требуют Inno Setup 6.7+.
WizardStyle=modern dark windows11 hidebevels includetitlebar
WizardSizePercent=110
WizardResizable=no
WizardBackColor=#101114
WizardBackImageFile=assets\pages\back_welcome.png
WizardBackImageOpacity=255
WizardImageFile=
WizardImageBackColor=none
WizardSmallImageFile=
WizardSmallImageBackColor=none
WizardImageOpacity=255

DisableWelcomePage=no
DisableReadyPage=no
DisableFinishedPage=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
Source: "..\dist\DeiLaw\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\pages\back_welcome.png"; Flags: dontcopy noencryption
Source: "assets\pages\back_directory.png"; Flags: dontcopy noencryption
Source: "assets\pages\back_tasks.png"; Flags: dontcopy noencryption
Source: "assets\pages\back_ready.png"; Flags: dontcopy noencryption
Source: "assets\pages\back_installing.png"; Flags: dontcopy noencryption
Source: "assets\pages\back_finish.png"; Flags: dontcopy noencryption

[Icons]
Name: "{group}\DeiLaw"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\DeiLaw"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить DeiLaw"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
var
  BackImagesPrepared: Boolean;

procedure PrepareBackImages;
begin
  if BackImagesPrepared then
    Exit;

  ExtractTemporaryFile('back_welcome.png');
  ExtractTemporaryFile('back_directory.png');
  ExtractTemporaryFile('back_tasks.png');
  ExtractTemporaryFile('back_ready.png');
  ExtractTemporaryFile('back_installing.png');
  ExtractTemporaryFile('back_finish.png');

  BackImagesPrepared := True;
end;

procedure SetDeiLawBackImage(const FileName: string);
var
  Images: TArrayOfGraphic;
begin
  PrepareBackImages;
  SetLength(Images, 1);
  Images[0] := TPngImage.Create;
  try
    Images[0].LoadFromFile(ExpandConstant('{tmp}\') + FileName);
    WizardSetBackImage(Images, True, True, 255);
  finally
    Images[0].Free;
  end;
end;

procedure SetPremiumPageText(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
  begin
    WizardForm.WelcomeLabel1.Caption := 'Добро пожаловать в DeiLaw';
    WizardForm.WelcomeLabel2.Caption :=
      'Установите DeiLaw — локальный RMRP Law Assistant.' + #13#10 + #13#10 +
      'Поиск по законодательству, памятка, Устав и RP-помощник в одном приложении.';
    WizardForm.NextButton.Caption := 'Далее';
  end
  else if CurPageID = wpSelectDir then
  begin
    WizardForm.PageNameLabel.Caption := 'Где установить DeiLaw';
    WizardForm.PageDescriptionLabel.Caption :=
      'Выберите папку программы. Рекомендуется оставить путь по умолчанию.';
    WizardForm.NextButton.Caption := 'Далее';
  end
  else if CurPageID = wpSelectTasks then
  begin
    WizardForm.PageNameLabel.Caption := 'Настройка быстрого запуска';
    WizardForm.PageDescriptionLabel.Caption :=
      'Выберите, нужен ли ярлык DeiLaw на рабочем столе.';
    WizardForm.NextButton.Caption := 'Далее';
  end
  else if CurPageID = wpReady then
  begin
    WizardForm.PageNameLabel.Caption := 'Всё готово';
    WizardForm.PageDescriptionLabel.Caption :=
      'Проверьте выбранные параметры и начните установку DeiLaw.';
    WizardForm.NextButton.Caption := 'Установить';
  end
  else if CurPageID = wpPreparing then
  begin
    WizardForm.PageNameLabel.Caption := 'Подготовка установки';
    WizardForm.PageDescriptionLabel.Caption :=
      'DeiLaw подготавливает необходимые файлы.';
  end
  else if CurPageID = wpInstalling then
  begin
    WizardForm.PageNameLabel.Caption := 'Устанавливаем DeiLaw';
    WizardForm.PageDescriptionLabel.Caption :=
      'Копируем файлы и создаём ярлыки. Это займёт немного времени.';
  end
  else if CurPageID = wpFinished then
  begin
    WizardForm.FinishedHeadingLabel.Caption := 'DeiLaw готов к работе';
    WizardForm.FinishedLabel.Caption :=
      'Установка успешно завершена.' + #13#10 + #13#10 +
      'Нажмите «Завершить», чтобы закрыть установщик. Если включён пункт запуска, DeiLaw откроется автоматически.';
    WizardForm.NextButton.Caption := 'Завершить';
  end;
end;

procedure UpdateDeiLawBackImage(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
    SetDeiLawBackImage('back_welcome.png')
  else if CurPageID = wpSelectDir then
    SetDeiLawBackImage('back_directory.png')
  else if CurPageID = wpSelectTasks then
    SetDeiLawBackImage('back_tasks.png')
  else if (CurPageID = wpReady) or (CurPageID = wpPreparing) then
    SetDeiLawBackImage('back_ready.png')
  else if CurPageID = wpInstalling then
    SetDeiLawBackImage('back_installing.png')
  else if CurPageID = wpFinished then
    SetDeiLawBackImage('back_finish.png')
  else
    SetDeiLawBackImage('back_welcome.png');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  UpdateDeiLawBackImage(CurPageID);
  SetPremiumPageText(CurPageID);
end;

procedure InitializeWizard;
begin
  WizardForm.Caption := 'DeiLaw — Установка';

  PrepareBackImages;
  SetDeiLawBackImage('back_welcome.png');
  SetPremiumPageText(wpWelcome);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
