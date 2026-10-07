PROGRAM PLC_PRG
VAR
    (* Deterministic demo for PUMP-DEMO: PUMP-01 (PUMP) *)
    StartCommand : BOOL := FALSE;
    StopCommand : BOOL := FALSE;
    PumpRunning : BOOL := FALSE;
    PumpFault : BOOL := FALSE;
    PumpState : INT := 0;
    PumpSpeed : REAL := 0.0;
    Pressure : REAL := 0.0;
    (* Modbus TCP image (16-bit words, mapped to Modbus_TCP_Server I/O) *)
    Mb_Pressure_W0 : WORD; (* IR0 Pressure REAL32 memory word 0 *)
    Mb_Pressure_W1 : WORD; (* IR1 Pressure REAL32 memory word 1 *)
    p_Pressure : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpSpeed_W0 : WORD; (* IR2 PumpSpeed REAL32 memory word 0 *)
    Mb_PumpSpeed_W1 : WORD; (* IR3 PumpSpeed REAL32 memory word 1 *)
    p_PumpSpeed : POINTER TO ARRAY[0..1] OF WORD;
    Mb_PumpState : WORD; (* IR4 PumpState INT16 READ *)
    Mb_StartCommand : BOOL; (* C144 StartCommand = HR9 PLC bit 8 *)
    Mb_StopCommand : BOOL; (* C145 StopCommand = HR9 PLC bit 9 *)
    Mb_PumpFault : BOOL; (* DI144 PumpFault = IR9 PLC bit 8 *)
    Mb_PumpRunning : BOOL; (* DI145 PumpRunning = IR9 PLC bit 9 *)
END_VAR

(* MODBUS IN: C144 StartCommand BOOL *)
StartCommand := Mb_StartCommand;

(* MODBUS IN: C145 StopCommand BOOL *)
StopCommand := Mb_StopCommand;

(* PUMP-01 : PUMP_BASIC_V1 state machine - 0 STOPPED, 1 STARTING, 2 RUNNING, 3 STOPPING, 9 FAULT *)
IF PumpFault = TRUE THEN
    PumpState := 9;
END_IF;
CASE PumpState OF
0: (* STOPPED *)
    PumpRunning := FALSE;
    IF StartCommand = TRUE AND StopCommand = FALSE THEN
        PumpState := 1;
    END_IF;
1: (* STARTING: simulated run feedback *)
    PumpRunning := TRUE;
    IF PumpRunning = TRUE THEN
        PumpState := 2;
    END_IF;
2: (* RUNNING *)
    IF StopCommand = TRUE THEN
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

(* MODBUS OUT: Pressure REAL32 (REAL memory -> register words) -> IR0..IR1 *)
p_Pressure := ADR(Pressure);
Mb_Pressure_W0 := p_Pressure^[0];
Mb_Pressure_W1 := p_Pressure^[1];

(* MODBUS OUT: PumpSpeed REAL32 (REAL memory -> register words) -> IR2..IR3 *)
p_PumpSpeed := ADR(PumpSpeed);
Mb_PumpSpeed_W0 := p_PumpSpeed^[0];
Mb_PumpSpeed_W1 := p_PumpSpeed^[1];

(* MODBUS OUT: PumpState INT16 -> IR4 *)
Mb_PumpState := INT_TO_WORD(PumpState);

(* MODBUS OUT: PumpFault BOOL -> DI144 *)
Mb_PumpFault := PumpFault;

(* MODBUS OUT: PumpRunning BOOL -> DI145 *)
Mb_PumpRunning := PumpRunning;
