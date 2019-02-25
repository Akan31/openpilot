import numpy as np
from cereal import car
from common.kalman.simple_kalman import KF1D
from selfdrive.config import Conversions as CV
from selfdrive.can.parser import CANParser
from selfdrive.car.mazda.values import DBC, CAR

def get_powertrain_can_parser(CP, canbus):
  # this function generates lists for signal, messages and initial values
  signals = [
    # sig_name, sig_address, default
    ("LEFT_BLINK", "BLINK_INFO", 0), 
    ("RIGHT_BLINK", "BLINK_INFO", 0),
    ("STEER_ANGLE", "STEER", 0),
    ("STEER_ANGLE_RATE", "STEER_RATE", 0),
    ("STEER_TORQUE_SENSOR", "STEER_TORQUE", 0),
    ("FL", "WHEEL_SPEEDS", 0), 
    ("FR", "WHEEL_SPEEDS", 0),
    ("RL", "WHEEL_SPEEDS", 0), 
    ("RR", "WHEEL_SPEEDS", 0), 
    ("CRZ_ACTIVE", "CRZ_CTRL", 0),
    ("STANDSTILL","PEDALS", 0),
    ("BRAKE_ON","PEDALS", 0),
    ("GEAR","GEAR", 0),
    ("DRIVER_SEATBELT", "SEATBELT", 0),
    ("FL", "DOORS", 0),
    ("GAS_PEDAL_PRESSED", "CRZ_EVENTS", 0),

    ("LINE1",      "CAM_LANETRACK", 0),
    ("CTR",        "CAM_LANETRACK", -1),
    ("LINE2",      "CAM_LANETRACK", 0),
    ("LANE_CURVE", "CAM_LANETRACK", 0),
    ("SIG1",       "CAM_LANETRACK", 0),
    ("SIG2",       "CAM_LANETRACK", 0),
    ("ZERO",       "CAM_LANETRACK", 0),
    ("SIG3",       "CAM_LANETRACK", 0),
    ("CHKSUM",     "CAM_LANETRACK", 0),
  ]
  
  checks = [
    # sig_address, frequency
    ("BLINK_INFO", 100),
    ("STEER", 20),
    ("STEER_RATE", 20),
    ("STEER_TORQUE", 20),
    ("WHEEL_SPEEDS", 20),
    ("CRZ_CTRL", 20),
    ("CRZ_EVENTS", 50),
    ("PEDALS", 20),
    ("SEATBELT", 100),
    ("DOORS", 100),
    ("GEAR", 50),
    ("CAM_LANETRACK", 60),
  ]

  return CANParser(DBC[CP.carFingerprint]['pt'], signals, checks, canbus.powertrain)

def get_cam_can_parser(CP, canbus):
  # this function generates lists for signal, messages and initial values
  signals = [
    # sig_name, sig_address, default
    ("LINE1",      "CAM_LANETRACK", 0),
    ("CTR",        "CAM_LANETRACK", -1),
    ("LINE2",      "CAM_LANETRACK", 0),
    ("LANE_CURVE", "CAM_LANETRACK", 0),
    ("SIG1",       "CAM_LANETRACK", 0),
    ("SIG2",       "CAM_LANETRACK", 0),
    ("ZERO",       "CAM_LANETRACK", 0),
    ("SIG3",       "CAM_LANETRACK", 0),
    ("CHKSUM",     "CAM_LANETRACK", 0),
  ]
  
  checks = [
    # sig_address, frequency
    ("CAM_LANETRACK", 60),
  ]

  return CANParser(DBC[CP.carFingerprint]['pt'], signals, checks, canbus.cam)
  
class CAM_LaneTrack(object):
  def __init__(self, ln1, ctr, ln2, lc, s1, s2, z, s3, ck):
    self.line1 = ln1
    self.ctr = ctr
    self.line2 = ln2
    self.lane_curve = lc
    self.sig1 = s1
    self.sig2 = s2
    self.zero = z
    self.sig3 = s3
    self.chksum = ck

class CarState(object):
  def __init__(self, CP, canbus):
    # initialize can parser
    self.CP = CP
    self.CAM_LT = CAM_LaneTrack(0, -1, 0, 0, 0, 0, 0, 0, 0)
    
    self.car_fingerprint = CP.carFingerprint
    self.blinker_on = False
    self.prev_blinker_on = False
    self.left_blinker_on = False
    self.prev_left_blinker_on = False
    self.right_blinker_on = False
    self.prev_right_blinker_on = False

    self.steer_torque_driver = 0
    self.steer_not_allowed = False

    self.main_on = False

    # vEgo kalman filter
    dt = 0.01
    self.v_ego_kf = KF1D(x0=np.matrix([[0.], [0.]]),
                         A=np.matrix([[1., dt], [0., 1.]]),
                         C=np.matrix([1., 0.]),
                         K=np.matrix([[0.12287673], [0.29666309]]))
    self.v_ego = 0.

  def updateCam(self, cam_cp):
    self.CAM_LT.line1      = cam_cp.vl["CAM_LANETRACK"]['LINE1']
    self.CAM_LT.ctr        = cam_cp.vl["CAM_LANETRACK"]['CTR']
    self.CAM_LT.line2      = cam_cp.vl["CAM_LANETRACK"]['LINE2']
    self.CAM_LT.line_curve = cam_cp.vl["CAM_LANETRACK"]['LANE_CURVE']
    self.CAM_LT.sig1       = cam_cp.vl["CAM_LANETRACK"]['SIG1']
    self.CAM_LT.sig2       = cam_cp.vl["CAM_LANETRACK"]['SIG2']
    self.CAM_LT.zero       = cam_cp.vl["CAM_LANETRACK"]['ZERO']
    self.CAM_LT.sig3       = cam_cp.vl["CAM_LANETRACK"]['SIG3']
    self.CAM_LT.chksum     = cam_cp.vl["CAM_LANETRACK"]['CHKSUM']

  
  def update(self, pt_cp):

    self.can_valid = pt_cp.can_valid
    self.can_valid = True
    
    self.v_wheel_fl = pt_cp.vl["WHEEL_SPEEDS"]['FL'] * CV.KPH_TO_MS
    self.v_wheel_fr = pt_cp.vl["WHEEL_SPEEDS"]['FR'] * CV.KPH_TO_MS
    self.v_wheel_rl = pt_cp.vl["WHEEL_SPEEDS"]['RL'] * CV.KPH_TO_MS
    self.v_wheel_rr = pt_cp.vl["WHEEL_SPEEDS"]['RR'] * CV.KPH_TO_MS
    speed_estimate = (self.v_wheel_fl + self.v_wheel_fr + self.v_wheel_rl + self.v_wheel_rr) / 4.0

    self.v_ego_raw = speed_estimate
    # FIXME
    v_ego_x = self.v_ego_kf.update(speed_estimate)
    self.v_ego = float(v_ego_x[0])
    self.a_ego = float(v_ego_x[1])

    self.prev_left_blinker_on = self.left_blinker_on
    self.prev_right_blinker_on = self.right_blinker_on
    self.prev_blinker_on = self.blinker_on
    self.left_blinker_on = pt_cp.vl["BLINK_INFO"]['LEFT_BLINK'] == 1
    self.right_blinker_on = pt_cp.vl["BLINK_INFO"]['RIGHT_BLINK'] == 1
    self.blinker_on = self.left_blinker_on or self.right_blinker_on

    self.acc_active = pt_cp.vl["CRZ_CTRL"]['CRZ_ACTIVE']
    self.main_on = pt_cp.vl["CRZ_CTRL"]['CRZ_ACTIVE']
      
    self.steer_torque_driver = pt_cp.vl["STEER_TORQUE"]['STEER_TORQUE_SENSOR']
    self.steer_override = abs(self.steer_torque_driver) > 150 #fixme

    self.angle_steers = pt_cp.vl["STEER"]['STEER_ANGLE'] 
    self.angle_steers_rate = pt_cp.vl["STEER_RATE"]['STEER_ANGLE_RATE']

    #self.standstill = pt_cp.vl["PEDALS"]['STANDSTILL'] == 1
    #self.brake_pressed = pt_cp.vl["PEDALS"]['BREAK_PEDAL_1'] == 1

    self.standstill = self.v_ego_raw < 0.01


