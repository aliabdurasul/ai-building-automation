(* MODBUS IN: HR0 Command word -> commands *)
StartCommand := Mb_Command.0;
StopCommand := Mb_Command.1;

(* MODBUS IN: HR1 TestInt16Write INT16 *)
TestInt16Write := WORD_TO_INT(Mb_TestInt16Write);

(* MODBUS IN: HR2..HR3 TestReal32Write REAL32 (register words -> REAL memory) *)
p_TestReal32Write := ADR(TestReal32Write);
p_TestReal32Write^[0] := Mb_TestReal32Write_W0;
p_TestReal32Write^[1] := Mb_TestReal32Write_W1;

(* MODBUS IN: HR4 TestUInt16Write UINT16 *)
TestUInt16Write := WORD_TO_UINT(Mb_TestUInt16Write);

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

(* MODBUS OUT: TestInt16Read INT16 -> IR1 *)
Mb_TestInt16Read := INT_TO_WORD(TestInt16Read);

(* MODBUS OUT: TestReal32Read REAL32 (REAL memory -> register words) -> IR2..IR3 *)
p_TestReal32Read := ADR(TestReal32Read);
Mb_TestReal32Read_W0 := p_TestReal32Read^[0];
Mb_TestReal32Read_W1 := p_TestReal32Read^[1];

(* MODBUS OUT: TestUInt16Read UINT16 -> IR4 *)
Mb_TestUInt16Read := UINT_TO_WORD(TestUInt16Read);
