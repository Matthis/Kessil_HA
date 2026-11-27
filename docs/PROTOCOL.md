# Kessil WiFi dongle – local protocol

Unofficial description of the local network interface of the Kessil WiFi dongle
(KSAWD01), written to make the dongle interoperable with Home Assistant. Everything
here was observed against a dongle with two A360X Tuna Sun lamps (lamp firmware
1.3 and 1.5, dongle firmware 1.5.13). Other lamp types and firmware versions may
behave differently.

Serial numbers, lamp IDs and network names below are placeholders.

## Transport

- TCP port **8888** on the dongle's IP. No authentication, no encryption – keep the
  dongle in a network segment you trust.
- Request: one raw JSON object `{"dtype": <int>, "data": {...}}`, no newline, no
  length prefix.
- Response: one JSON object, possibly spread over several lines/TCP segments. Read
  until a complete JSON object has arrived.
- Every response carries `code` (`0` = success, negative = error) and `msg`; most
  carry `dType` (echo of the request type).
- Unknown command or bad parameters:
  `{"msg":"Invalid command or parameters","code":-1,"dType":-1}`
- One connection per command works reliably. Do not send commands in parallel.

Quick test:

```sh
printf '{"dtype":117,"data":{}}' | nc -w 3 <dongle-ip> 8888
```

## Commands

✅ = verified on a real device. Commands marked ⚠️ change the light or the dongle.

| dtype | Purpose | data | Status |
|---|---|---|---|
| 0 | List lamps (same as 5) | `{}` | ✅ |
| 2 | Identify lamp (blinks) ⚠️ | `KID` | not tested |
| 3 | Set manual channel values ⚠️ | `GID`, `UI1`…`UI5`, `save`, `enabled` | ✅ |
| 5 | List lamps | `{}` | ✅ |
| 100 | Run program ⚠️ | `GID`, `PID` (`0` = manual) | ✅ |
| 102 | Group state | `GID` | ✅ |
| 105 | Program IDs per lamp type | `{}` | ✅ |
| 106 | Program details (curve points) | `PID`, `type` | ✅ |
| 113 | Pause group ⚠️ | `GID`, `pause` (`1`/`0`) | ✅ accepted |
| 114 | System info | `{}` | ✅ |
| 117 | Dongle serial / siblings | `{}` | ✅ |

Commands in the 200 range manage the dongle itself (Wi-Fi, clock, firmware, reboot).
This integration never sends them, and you should not either unless you know how
to recover the dongle.

## Responses

### 117 – serial

```json
{"msg":"Success","code":0,"dType":117,"SN":"DONGLE0001","siblings":"DONGLE0001","APEX":0}
```

### 5 – lamps

```json
{"code":0,"msg":"Success","dType":5,"lamps":[
 {"KID":10000001,"GID":2,"lGID":-1,"rGID":-1,"model":"A360X Tuna Sun","FWVer":"1.3","type":2,"temp":0,"timestamp":1795804440},
 {"KID":10000002,"GID":2,"lGID":-1,"rGID":-1,"model":"A360X Tuna Sun","FWVer":"1.5","type":2,"temp":0,"timestamp":1795804440}]}
```

- `KID`: lamp ID, `GID`: group the lamp belongs to.
- `temp`: `0` in normal operation; presumably non-zero when the lamp overheats.

### 114 – system info

```json
{"code":0,"msg":"Success","dType":114,"sn":"DONGLE0001","ver":"1.5.13","SSID":"MyIoTNetwork",
 "ENC":"psk2","timezone":"Europe/Berlin","demo":0,"BAND":1,"lamps":[ ... as in 5 ... ],
 "num_prog_ids":{"TB":[{"PID":0,"order":0},{"PID":1,"order":1}],
                 "TS":[{"PID":0,"order":0},{"PID":1,"order":1},{"PID":3,"order":2}], ...},
 "group_ids":[1,2,26,27]}
```

The dongle always has one default group per lamp type (here 1, 2, 26, 27); only
groups that actually contain lamps are interesting.

### 102 – group

```json
{"msg":"Success","code":0,"dType":102,"group":{"gid":2,"pid":3,"eid":-1,"type":2,"hasLamps":2,
 "name":"Default TS","pause":0,"startDate":1774368396,"UI":[128,117,0,78,56],
 "accl":{"start":20,"period":14,"enabled":0,"startDate":0,"stopDate":0},
 "lunar":{"start":1200,"end":480,"high":120,"color":0,"phase":0,"enabled":0,"startDate":0,"stopDate":0}}}
```

| Field | Meaning |
|---|---|
| `pid` | Active program. `0` or `-1` = manual. |
| `type` | Lamp type: `0` 0-10V, `1` Tuna Blue, `2` Tuna Sun, `3` Refugium |
| `hasLamps` | Number of lamps in the group |
| `pause` | `1` while the group is paused |
| `UI` | Stored **manual** channel values (0–255). While a program runs, this is *not* the lamps' current output – compute that from the program curve (106). |
| `accl` / `lunar` | Acclimation and moon-phase settings (not used by this integration yet) |

Program-list keys per type: `Z2T` (0), `TB` (1), `TS` (2), `RF` (3).

### Channels for Tuna Sun (type 2)

| Index | Field in dtype 3 | Channel | Range |
|---|---|---|---|
| 0 | `UI1` | Intensity | 0–255 |
| 1 | `UI2` | Light color (warm → cool white) | 0–255 |
| 2 | `UI3` | unused | 0 |
| 3 | `UI4` | Red | 0–100 |
| 4 | `UI5` | Amber | 0–100 |

Values above 100 for red or amber are rejected with
`{"msg":"Invalid command format","code":-1}`. Percent for intensity and color is
`round(raw / 255 * 100)`; red and amber are already percent.

### 105 – program IDs

```json
{"msg":"Success","code":0,"dType":105,"prog_ids":{"TS":[{"PID":0,"order":0},{"PID":1,"order":1},{"PID":3,"order":2}], ...}}
```

`PID 0` is the manual setting and has no curve (`106` returns an error for it).

### 106 – program

Request `{"dtype":106,"data":{"PID":1,"type":2}}`:

```json
{"msg":"Success","code":0,"program":{"PID":1,"order":1,"type":2,"name":"Preset Tuna Sun","points":[
 {"minutes":480,"UI":[2,0,0,0,0],"eid":-1,"duration":30,"freq":1},
 {"minutes":540,"UI":[51,25,0,0,0],"eid":-1,"duration":30,"freq":1},
 ...
 {"minutes":1200,"UI":[0,0,0,0,0],"eid":-1,"duration":30,"freq":1}]},"dType":106}
```

- `minutes`: minutes after midnight (dongle clock, see `timezone` in 114).
- `UI`: channel values at that point; the dongle fades between points.
- `eid` ≥ 0 marks an effect at that point (`duration` in seconds, `freq`).

## Control sequences

**Set the light manually (persistent)**

1. `{"dtype":100,"data":{"GID":2,"PID":0}}` – switch the group to manual. The lamps
   jump to the last stored manual values.
2. `{"dtype":3,"data":{"GID":2,"UI1":128,"UI2":117,"UI3":0,"UI4":78,"UI5":56,"save":1,"enabled":1}}`

   After this the group reports `pid` `-1`.

**Back to a program**: `{"dtype":100,"data":{"GID":2,"PID":3}}` – `UI` keeps the
manual values from step 2 although the lamps follow the program again.

**Pause / resume**: `{"dtype":113,"data":{"GID":2,"pause":1}}`, then `"pause":0`.
The response contains the full group object (as in 102) with `pause` set; `pid`
and the stored manual `UI` are not changed. (Visible effect on the lamps not yet
confirmed.)

**Preview without switching**: `dtype 3` with `"save":0` shows the values for about
one second, then the running program takes over again.
