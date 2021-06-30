import rospy
import time
from operator import itemgetter
from std_msgs.msg import Float64
from sensor_msgs.msg import JointState
from gazebo_msgs.srv import GetModelState
from gazebo_msgs.srv import SetModelState
from gazebo_msgs.msg import ModelState

class Robot:

    def __init__(self):
        rospy.init_node('SchunkRL')

        # ROS topics for controlling the Finger joints
        topic_1 = rospy.Publisher('/robot/arm_1_joint/cmd_pos', Float64, queue_size=10)
        topic_2 = rospy.Publisher('/robot/arm_2_joint/cmd_pos', Float64)
        topic_3 = rospy.Publisher('/robot/arm_3_joint/cmd_pos', Float64)
        topic_4 = rospy.Publisher('/robot/arm_4_joint/cmd_pos', Float64)
        topic_5 = rospy.Publisher('/robot/arm_5_joint/cmd_pos', Float64)
        topic_6 = rospy.Publisher('/robot/arm_6_joint/cmd_pos', Float64)

        self.joint_topics = [topic_1, topic_2, topic_3, topic_4, topic_5, topic_6]

        rospy.wait_for_service("gazebo/get_model_state", 10.0)
        rospy.wait_for_service("gazebo/set_model_state", 10.0)
        self.__get_pose_srv = rospy.ServiceProxy("gazebo/get_model_state", GetModelState)
        self.__set_pose_srv = rospy.ServiceProxy("gazebo/set_model_state", SetModelState)

        # get the initial state of the blue object
        self.object_init_state = ModelState()
        self.object_init_state.model_name = 'BLUE_cylinder'
        self.object_init_state.pose = self.__get_pose_srv('BLUE_cylinder', 'world').pose
        self.object_init_state.scale = self.__get_pose_srv('BLUE_cylinder', 'world').scale
        self.object_init_state.pose.position.x = -0.380242735867
        self.object_init_state.pose.position.y = -0.256517463776
        self.object_init_state.pose.position.z = 1.12013355538
        self.object_init_state.pose.orientation.x = 0.000772991735408
        self.object_init_state.pose.orientation.y = -0.000885429290148
        self.object_init_state.pose.orientation.z = 0.00401944480518
        self.object_init_state.pose.orientation.w = 0.999991231243
        self.object_init_state.scale.x=1.0
        self.object_init_state.scale.y=1.0
        self.object_init_state.scale.z=1.0
        # Variables that hold finger states
        self.__current_state = [None]

        rospy.Subscriber("/robot/joint_states", JointState, self.__on_joint_state)

    def __on_joint_state(self, msg):
        timestamp = (msg.header.stamp.secs, msg.header.stamp.nsecs)
        indices = (msg.name.index('arm_1_joint'),
                   msg.name.index('arm_2_joint'),
                   msg.name.index('arm_3_joint'),
                   msg.name.index('arm_4_joint'),
                   msg.name.index('arm_5_joint'),
                   msg.name.index('arm_6_joint'))
        self.__current_state[0] = (itemgetter(*indices)(msg.position), timestamp)

    def reset(self):
        """
        Resets robot joint to the initial state
        """
        for topic in self.joint_topics:
            topic.publish(Float64(0.0))

        reset_obj = self.__set_pose_srv(self.object_init_state)  # reset the 'BLUE_cylinder' & print status
        print(reset_obj)

    def reset_object(self):
        reset_obj = self.__set_pose_srv(self.object_init_state)
        
    def get_current_state(self):
        """
        Returns the current state of the environment. The state is a tuple, where the first entry is
        a list of the six joint positions, and the second entry is the pose of the cylinder
        """
        # current time
        now = rospy.get_rostime() - rospy.Time(secs=0)

        # ensure that the timestamp of the joint states is greater than the current time
        while (now + rospy.Duration(0, 500000000)) > rospy.Duration(self.__current_state[0][1][0],
                                                                    self.__current_state[0][1][1]):
            rospy.sleep(0.1)
        return self.__current_state[0][:-1][0], self.__get_pose_srv('BLUE_cylinder', 'world').pose, \
               self.__get_pose_srv('robot', 'COL_COL_COL_VIS_VIS_VIS_VIS_VIS_VIS_VIS_VIS_VIS_hollie_real.006').pose


    def act(self, j1, j2, j3, j4, j5, j6):
        """
        Takes an action by setting the six join positions
        """
        self.joint_topics[0].publish(Float64(j1))
        self.joint_topics[1].publish(Float64(j2))
        self.joint_topics[2].publish(Float64(j3))
        self.joint_topics[3].publish(Float64(j4))
        self.joint_topics[4].publish(Float64(j5))
        self.joint_topics[5].publish(Float64(j6))

# to get position of robot's hand, using:
# self.__get_pose_srv('robot', 'COL_COL_COL_VIS_VIS_VIS_VIS_VIS_VIS_VIS_VIS_VIS_hollie_real.005')
robot = Robot()
time.sleep(5)
robot.reset()