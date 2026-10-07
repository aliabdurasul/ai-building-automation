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
    FanSpeed : REAL := 50.0;
    HeatingValve : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_Setpoint_W0 : WORD; (* HR1 Setpoint REAL32 memory word 0 *)
    Mb_Setpoint_W1 : WORD; (* HR2 Setpoint REAL32 memory word 1 *)
    p_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_Setpoint_W0_prev : WORD;
    Mb_Setpoint_W1_prev : WORD;
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_FanSpeed_W0 : WORD; (* IR1 FanSpeed REAL32 memory word 0 *)
    Mb_FanSpeed_W1 : WORD; (* IR2 FanSpeed REAL32 memory word 1 *)
    p_FanSpeed : POINTER TO ARRAY[0..1] OF WORD;
    Mb_HeatingValve_W0 : WORD; (* IR3 HeatingValve REAL32 memory word 0 *)
    Mb_HeatingValve_W1 : WORD; (* IR4 HeatingValve REAL32 memory word 1 *)
    p_HeatingValve : POINTER TO ARRAY[0..1] OF WORD;
    Mb_SupplyTemp_W0 : WORD; (* IR5 SupplyTemp REAL32 memory word 0 *)
    Mb_SupplyTemp_W1 : WORD; (* IR6 SupplyTemp REAL32 memory word 1 *)
    p_SupplyTemp : POINTER TO ARRAY[0..1] OF WORD;
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

(* MODBUS OUT: FanSpeed REAL32 (REAL memory -> register words) -> IR1..IR2 *)
p_FanSpeed := ADR(FanSpeed);
Mb_FanSpeed_W0 := p_FanSpeed^[0];
Mb_FanSpeed_W1 := p_FanSpeed^[1];

(* MODBUS OUT: HeatingValve REAL32 (REAL memory -> register words) -> IR3..IR4 *)
p_HeatingValve := ADR(HeatingValve);
Mb_HeatingValve_W0 := p_HeatingValve^[0];
Mb_HeatingValve_W1 := p_HeatingValve^[1];

(* MODBUS OUT: SupplyTemp REAL32 (REAL memory -> register words) -> IR5..IR6 *)
p_SupplyTemp := ADR(SupplyTemp);
Mb_SupplyTemp_W0 := p_SupplyTemp^[0];
Mb_SupplyTemp_W1 := p_SupplyTemp^[1];
