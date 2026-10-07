PROGRAM PLC_PRG
VAR
    (* Deterministic demo for AHU-01 *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    FanCommand : BOOL := FALSE;
    FanRunning : BOOL := FALSE;
    FanFault : BOOL := FALSE;
    SupplyTemp : REAL := 21.0;
    Setpoint : REAL := 22.0;
    HeatingValve : REAL := 0.0;
    ReturnTemp : REAL := 19.5;
    AHU02_Setpoint : REAL := 22.0;
    AHU02_Enable : BOOL := FALSE;
    TestReal32Read : REAL := 21.5;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_Setpoint_W0 : WORD; (* HR1 Setpoint REAL32 memory word 0 *)
    Mb_Setpoint_W1 : WORD; (* HR2 Setpoint REAL32 memory word 1 *)
    p_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_Setpoint_W0_prev : WORD;
    Mb_Setpoint_W1_prev : WORD;
    Mb_AHU02_Setpoint_W0 : WORD; (* HR3 AHU02_Setpoint REAL32 memory word 0 *)
    Mb_AHU02_Setpoint_W1 : WORD; (* HR4 AHU02_Setpoint REAL32 memory word 1 *)
    p_AHU02_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_AHU02_Setpoint_W0_prev : WORD;
    Mb_AHU02_Setpoint_W1_prev : WORD;
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_SupplyTemp_W0 : WORD; (* IR3 SupplyTemp REAL32 memory word 0 *)
    Mb_SupplyTemp_W1 : WORD; (* IR4 SupplyTemp REAL32 memory word 1 *)
    p_SupplyTemp : POINTER TO ARRAY[0..1] OF WORD;
    Mb_TestReal32Read_W0 : WORD; (* IR5 TestReal32Read REAL32 memory word 0 *)
    Mb_TestReal32Read_W1 : WORD; (* IR6 TestReal32Read REAL32 memory word 1 *)
    p_TestReal32Read : POINTER TO ARRAY[0..1] OF WORD;
    Mb_ReturnTemp_W0 : WORD; (* IR7 ReturnTemp REAL32 memory word 0 *)
    Mb_ReturnTemp_W1 : WORD; (* IR8 ReturnTemp REAL32 memory word 1 *)
    p_ReturnTemp : POINTER TO ARRAY[0..1] OF WORD;
    Mb_AHU02_Enable : BOOL; (* C144 AHU02_Enable = HR9 PLC bit 8 *)
    Mb_FanRunning : BOOL; (* DI144 FanRunning = IR9 PLC bit 8 *)
END_VAR

(* MODBUS IN: HR0 Command word -> commands *)
StartCommand := Mb_Command.0;
StopCommand := Mb_Command.1;

(* MODBUS IN: HR1..HR2 Setpoint REAL32 (register words -> REAL memory) *)
IF Mb_Setpoint_W0 <> Mb_Setpoint_W0_prev OR Mb_Setpoint_W1 <> Mb_Setpoint_W1_prev THEN
    p_Setpoint := ADR(Setpoint);
    p_Setpoint^[0] := Mb_Setpoint_W0;
    p_Setpoint^[1] := Mb_Setpoint_W1;
    Mb_Setpoint_W0_prev := Mb_Setpoint_W0;
    Mb_Setpoint_W1_prev := Mb_Setpoint_W1;
END_IF;

(* MODBUS IN: HR3..HR4 AHU02_Setpoint REAL32 (register words -> REAL memory) *)
IF Mb_AHU02_Setpoint_W0 <> Mb_AHU02_Setpoint_W0_prev OR Mb_AHU02_Setpoint_W1 <> Mb_AHU02_Setpoint_W1_prev THEN
    p_AHU02_Setpoint := ADR(AHU02_Setpoint);
    p_AHU02_Setpoint^[0] := Mb_AHU02_Setpoint_W0;
    p_AHU02_Setpoint^[1] := Mb_AHU02_Setpoint_W1;
    Mb_AHU02_Setpoint_W0_prev := Mb_AHU02_Setpoint_W0;
    Mb_AHU02_Setpoint_W1_prev := Mb_AHU02_Setpoint_W1;
END_IF;

(* MODBUS IN: C144 AHU02_Enable BOOL *)
AHU02_Enable := Mb_AHU02_Enable;

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

(* MODBUS OUT: SupplyTemp REAL32 (REAL memory -> register words) -> IR3..IR4 *)
p_SupplyTemp := ADR(SupplyTemp);
Mb_SupplyTemp_W0 := p_SupplyTemp^[0];
Mb_SupplyTemp_W1 := p_SupplyTemp^[1];

(* MODBUS OUT: TestReal32Read REAL32 (REAL memory -> register words) -> IR5..IR6 *)
p_TestReal32Read := ADR(TestReal32Read);
Mb_TestReal32Read_W0 := p_TestReal32Read^[0];
Mb_TestReal32Read_W1 := p_TestReal32Read^[1];

(* MODBUS OUT: ReturnTemp REAL32 (REAL memory -> register words) -> IR7..IR8 *)
p_ReturnTemp := ADR(ReturnTemp);
Mb_ReturnTemp_W0 := p_ReturnTemp^[0];
Mb_ReturnTemp_W1 := p_ReturnTemp^[1];

(* MODBUS OUT: FanRunning BOOL -> DI144 *)
Mb_FanRunning := FanRunning;
