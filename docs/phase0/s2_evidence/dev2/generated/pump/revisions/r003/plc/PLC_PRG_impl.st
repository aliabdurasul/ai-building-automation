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

(* MODBUS OUT: PumpSpeed REAL32 (REAL memory -> register words) -> IR2..IR3 *)
p_PumpSpeed := ADR(PumpSpeed);
Mb_PumpSpeed_W0 := p_PumpSpeed^[0];
Mb_PumpSpeed_W1 := p_PumpSpeed^[1];

(* MODBUS OUT: PumpState INT16 -> IR4 *)
Mb_PumpState := INT_TO_WORD(PumpState);

(* MODBUS OUT: FlowRate REAL32 (REAL memory -> register words) -> IR5..IR6 *)
p_FlowRate := ADR(FlowRate);
Mb_FlowRate_W0 := p_FlowRate^[0];
Mb_FlowRate_W1 := p_FlowRate^[1];

(* MODBUS OUT: PumpFault BOOL -> DI144 *)
Mb_PumpFault := PumpFault;

(* MODBUS OUT: PumpRunning BOOL -> DI145 *)
Mb_PumpRunning := PumpRunning;
