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

(* AHU-01 : AHU_SEQ_V1 - 0 STOPPED, 1 STARTING, 2 DAMPER OPENING, 3 FAN STARTING, 4 RUNNING, 5 STOPPING, 6 DAMPER CLOSING, 9 FAULT *)
NowMs := TIME_TO_UDINT(TIME());
FanFault := FanFailure;
DamperFault := DamperFailure;
AhuAlarm := FanFailure OR DamperFailure;
IF AhuAlarm AND AhuState <> 9 THEN
    AhuState := 9;
    StateTrace := StateTrace OR 16#0200;
    StateEntryMs := NowMs;
END_IF;
CASE AhuState OF
0: (* STOPPED *)
    FanCommand := FALSE;
    FanRunning := FALSE;
    DamperCommand := FALSE;
    DamperOpen := FALSE;
    IF StartCommand AND NOT StartPrev AND NOT StopCommand THEN
        SequenceStarts := SequenceStarts + 1;
        StateTrace := 16#0002;
        AhuState := 1;
        StateEntryMs := NowMs;
    END_IF;
1: (* STARTING *)
    AhuState := 2;
    StateTrace := StateTrace OR 16#0004;
    StateEntryMs := NowMs;
2: (* DAMPER OPENING *)
    DamperCommand := TRUE;
    IF StopCommand AND NOT StopPrev THEN
        SequenceStops := SequenceStops + 1;
        AhuState := 5;
        StateTrace := StateTrace OR 16#0020;
        StateEntryMs := NowMs;
    ELSIF NowMs - StateEntryMs >= 2000 THEN
        DamperOpen := TRUE;
        AhuState := 3;
        StateTrace := StateTrace OR 16#0008;
        StateEntryMs := NowMs;
    END_IF;
3: (* FAN STARTING *)
    FanCommand := TRUE;
    IF StopCommand AND NOT StopPrev THEN
        SequenceStops := SequenceStops + 1;
        AhuState := 5;
        StateTrace := StateTrace OR 16#0020;
        StateEntryMs := NowMs;
    ELSIF NowMs - StateEntryMs >= 1000 THEN
        FanRunning := TRUE;
        AhuState := 4;
        StateTrace := StateTrace OR 16#0010;
        StateEntryMs := NowMs;
    END_IF;
4: (* RUNNING *)
    IF StopCommand AND NOT StopPrev THEN
        SequenceStops := SequenceStops + 1;
        AhuState := 5;
        StateTrace := StateTrace OR 16#0020;
        StateEntryMs := NowMs;
    END_IF;
5: (* STOPPING: fan run-down *)
    FanCommand := FALSE;
    IF NowMs - StateEntryMs >= 1000 THEN
        FanRunning := FALSE;
        AhuState := 6;
        StateTrace := StateTrace OR 16#0040;
        StateEntryMs := NowMs;
    END_IF;
6: (* DAMPER CLOSING *)
    DamperCommand := FALSE;
    IF NowMs - StateEntryMs >= 2000 THEN
        DamperOpen := FALSE;
        AhuState := 0;
        StateTrace := StateTrace OR 16#0001;
        StateEntryMs := NowMs;
    END_IF;
9: (* FAULT: safe state *)
    FanCommand := FALSE;
    FanRunning := FALSE;
    DamperCommand := FALSE;
    DamperOpen := FALSE;
    IF NOT AhuAlarm THEN
        AhuState := 0;
        StateTrace := StateTrace OR 16#0001;
        StateEntryMs := NowMs;
    END_IF;
ELSE (* unknown state value: safe fallback *)
    FanCommand := FALSE;
    FanRunning := FALSE;
    DamperCommand := FALSE;
    DamperOpen := FALSE;
    AhuState := 0;
    StateEntryMs := NowMs;
END_CASE;
StartPrev := StartCommand;
StopPrev := StopCommand;

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

(* MODBUS OUT: AhuState INT16 -> IR1 *)
Mb_AhuState := INT_TO_WORD(AhuState);

(* MODBUS OUT: HeatingValve REAL32 (REAL memory -> register words) -> IR2..IR3 *)
p_HeatingValve := ADR(HeatingValve);
Mb_HeatingValve_W0 := p_HeatingValve^[0];
Mb_HeatingValve_W1 := p_HeatingValve^[1];

(* MODBUS OUT: SequenceStarts UINT16 -> IR4 *)
Mb_SequenceStarts := UINT_TO_WORD(SequenceStarts);

(* MODBUS OUT: SequenceStops UINT16 -> IR5 *)
Mb_SequenceStops := UINT_TO_WORD(SequenceStops);

(* MODBUS OUT: StateTrace WORD -> IR6 *)
Mb_StateTrace := StateTrace;

(* MODBUS OUT: SupplyTemp REAL32 (REAL memory -> register words) -> IR7..IR8 *)
p_SupplyTemp := ADR(SupplyTemp);
Mb_SupplyTemp_W0 := p_SupplyTemp^[0];
Mb_SupplyTemp_W1 := p_SupplyTemp^[1];

(* MODBUS OUT: AhuAlarm BOOL -> DI144 *)
Mb_AhuAlarm := AhuAlarm;

(* MODBUS OUT: DamperCommand BOOL -> DI145 *)
Mb_DamperCommand := DamperCommand;

(* MODBUS OUT: DamperFault BOOL -> DI146 *)
Mb_DamperFault := DamperFault;

(* MODBUS OUT: DamperOpen BOOL -> DI147 *)
Mb_DamperOpen := DamperOpen;

(* MODBUS OUT: FanRunning BOOL -> DI148 *)
Mb_FanRunning := FanRunning;
