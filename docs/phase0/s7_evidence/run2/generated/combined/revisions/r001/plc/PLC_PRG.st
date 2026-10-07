PROGRAM PLC_PRG
VAR
    (* Deterministic demo for BMS-DEMO: AHU-01 (AHU), PUMP-01 (PUMP) *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    FanCommand : BOOL := FALSE;
    FanRunning : BOOL := FALSE;
    FanFault : BOOL := FALSE;
    SupplyTemp : REAL := 21.0;
    Setpoint : REAL := 22.0;
    HeatingValve : REAL := 0.0;
    PUMP01_StartCommand : BOOL := FALSE;
    PUMP01_StopCommand : BOOL := FALSE;
    PumpRunning : BOOL := FALSE;
    PumpFault : BOOL := FALSE;
    PumpState : INT := 0;
    PumpSpeed : REAL := 0.0;
    Pressure : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Command : WORD; (* HR0 Command: bit0=StartCommand, bit1=StopCommand *)
    Mb_Setpoint_W0 : WORD; (* HR1 Setpoint REAL32 memory word 0 *)
    Mb_Setpoint_W1 : WORD; (* HR2 Setpoint REAL32 memory word 1 *)
    p_Setpoint : POINTER TO ARRAY[0..1] OF WORD;
    Mb_Setpoint_W0_prev : WORD;
    Mb_Setpoint_W1_prev : WORD;
    Mb_Status : WORD; (* IR0 Status: bit0=FanCommand, bit1=FanRunning, bit2=FanFault *)
    Mb_Pressure_W0 : WORD; (* IR1 Pressure REAL32 memory word 0 *)
    Mb_Pressure_W1 : WORD; (* IR2 Pressure REAL32 memory word 1 *)
    p_Pressure : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpSpeed_W0 : WORD; (* IR3 PumpSpeed REAL32 memory word 0 *)
    Mb_PumpSpeed_W1 : WORD; (* IR4 PumpSpeed REAL32 memory word 1 *)
    p_PumpSpeed : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpState : WORD; (* IR5 PumpState INT16 READ *)
    Mb_SupplyTemp_W0 : WORD; (* IR6 SupplyTemp REAL32 memory word 0 *)
    Mb_SupplyTemp_W1 : WORD; (* IR7 SupplyTemp REAL32 memory word 1 *)
    p_SupplyTemp : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PUMP01_StartCommand : BOOL; (* C144 PUMP01_StartCommand = HR9 PLC bit 8 *)
    Mb_PUMP01_StopCommand : BOOL; (* C145 PUMP01_StopCommand = HR9 PLC bit 9 *)
    Mb_FanRunning : BOOL; (* DI144 FanRunning = IR9 PLC bit 8 *)
    Mb_PumpFault : BOOL; (* DI145 PumpFault = IR9 PLC bit 9 *)
    Mb_PumpRunning : BOOL; (* DI146 PumpRunning = IR9 PLC bit 10 *)
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

(* MODBUS IN: C144 PUMP01_StartCommand BOOL *)
PUMP01_StartCommand := Mb_PUMP01_StartCommand;

(* MODBUS IN: C145 PUMP01_StopCommand BOOL *)
PUMP01_StopCommand := Mb_PUMP01_StopCommand;

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

(* PUMP-01 : PUMP_BASIC_V1 state machine - 0 STOPPED, 1 STARTING, 2 RUNNING, 3 STOPPING, 9 FAULT *)
IF PumpFault = TRUE THEN
    PumpState := 9;
END_IF;
CASE PumpState OF
0: (* STOPPED *)
    PumpRunning := FALSE;
    IF PUMP01_StartCommand = TRUE AND PUMP01_StopCommand = FALSE THEN
        PumpState := 1;
    END_IF;
1: (* STARTING: simulated run feedback *)
    PumpRunning := TRUE;
    IF PumpRunning = TRUE THEN
        PumpState := 2;
    END_IF;
2: (* RUNNING *)
    IF PUMP01_StopCommand = TRUE THEN
        PumpState := 3;
    END_IF;
3: (* STOPPING *)
    PumpRunning := FALSE;
    IF PumpRunning = FALSE THEN
        PumpState := 0;
    END_IF;
9: (* FAULT *)
    PumpRunning := FALSE;
    IF PumpFault = FALSE THEN
        PumpState := 0;
    END_IF;
ELSE
    PumpState := 0;
END_CASE;

(* MODBUS OUT: status -> IR0 Status word *)
Mb_Status := 0;
Mb_Status.0 := FanCommand;
Mb_Status.1 := FanRunning;
Mb_Status.2 := FanFault;

(* MODBUS OUT: Pressure REAL32 (REAL memory -> register words) -> IR1..IR2 *)
p_Pressure := ADR(Pressure);
Mb_Pressure_W0 := p_Pressure^[0];
Mb_Pressure_W1 := p_Pressure^[1];

(* MODBUS OUT: PumpSpeed REAL32 (REAL memory -> register words) -> IR3..IR4 *)
p_PumpSpeed := ADR(PumpSpeed);
Mb_PumpSpeed_W0 := p_PumpSpeed^[0];
Mb_PumpSpeed_W1 := p_PumpSpeed^[1];

(* MODBUS OUT: PumpState INT16 -> IR5 *)
Mb_PumpState := INT_TO_WORD(PumpState);

(* MODBUS OUT: SupplyTemp REAL32 (REAL memory -> register words) -> IR6..IR7 *)
p_SupplyTemp := ADR(SupplyTemp);
Mb_SupplyTemp_W0 := p_SupplyTemp^[0];
Mb_SupplyTemp_W1 := p_SupplyTemp^[1];

(* MODBUS OUT: FanRunning BOOL -> DI144 *)
Mb_FanRunning := FanRunning;

(* MODBUS OUT: PumpFault BOOL -> DI145 *)
Mb_PumpFault := PumpFault;

(* MODBUS OUT: PumpRunning BOOL -> DI146 *)
Mb_PumpRunning := PumpRunning;
