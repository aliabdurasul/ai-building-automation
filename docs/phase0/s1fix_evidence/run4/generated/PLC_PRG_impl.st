(* MODBUS IN: HR0 Command word -> commands *)
StartCommand := Mb_Command.0;
StopCommand := Mb_Command.1;

(* FAN START *)
IF StartCommand = TRUE AND FanFault = FALSE THEN
    FanCommand := TRUE;
    FanRunning := TRUE;
END_IF;

(* FAN STOP *)
IF StopCommand = TRUE THEN
    FanCommand := FALSE;
    FanRunning := FALSE;
END_IF;

(* FAN FAULT *)
IF FanFault = TRUE THEN
    FanCommand := FALSE;
    FanRunning := FALSE;
END_IF;

(* HEATING - simple demo, not PID *)
IF SupplyTemp < Setpoint THEN
    HeatingValve := 100.0;
ELSE
    HeatingValve := 0.0;
END_IF;

(* MODBUS OUT: status -> IR0 Status word *)
Mb_Status := 0;
Mb_Status.0 := FanCommand;
Mb_Status.1 := FanRunning;
Mb_Status.2 := FanFault;
