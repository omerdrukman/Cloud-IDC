from flask import Flask, request, session
import time
import uuid
import os
import requests
import random
import boto3

ec2 = boto3.resource('ec2', region_name='us-east-1')
ec2Client = boto3.client('ec2', region_name='us-east-1')

app = Flask(__name__)
app.secret_key = 'some-key'
PORT=5000

# other_router_ip='localhost'

wating_jobs_queue = []
finish_jobs_queue = []
workers = []

workload_count = 0

other_router_ip = os.environ.get('OTHER_IP')


@app.route('/enqueue', methods=['PUT'])
def enqueue():
     args = request.args

     iterations = int(args.get('iterations'))
     buffer = str(request.files['data'].stream.read())

     task_id = str(uuid.uuid1())
     task_time = time.time()

     wating_jobs_queue.append((task_id, task_time, buffer, iterations))

     if len(workers) == 0:
          workers.append(1)
          print('spawn worker')

     return task_id, 200

@app.route('/pullCompleted',  methods=['POST'])
def pullCompleted():
     args = request.args

     top = int(args.get('top'))

     try:
          # get done tasks
          res = requests.get(f'http://{other_router_ip}:{PORT}/getCompleteQueue')

          if res.status_code != 200:
               other_queue = []
          else:
               other_queue = res.json()['finish_jobs_queue']
     except:
          other_queue = []

     completed_jobs = finish_jobs_queue + other_queue
     random.shuffle(completed_jobs)
     return {'data': [{'work_id': x[0], 'result':x[1]} for x in completed_jobs[:top]]}, 200

@app.route('/getWork',  methods=['GET'])
def getWork():
     global workload_count
     if len(wating_jobs_queue) > 0:
          job = wating_jobs_queue[-1]
          wating_jobs_queue.pop()

          print(time.time() - job[1])
          if time.time() - job[1] > 3:
               spawn_worker()
               workload_count = 0
          else:
               workload_count += 1

               if workload_count >= 10 and len(workers) > 1:
                    workload_count = 0

                    worker_id = workers[-1]
                    ec2.instances.filter(InstanceIds=[worker_id]).terminate()
                    print('shutdown worker')

          return {'job': job}, 200

     try:
          # get wating tasks
          res = requests.get(f'http://{other_router_ip}:{PORT}/getWaitingQueue')
     except:
          return '', 400

     if res.status_code != 200:
          other_queue = None
     else:
          return res.json(), 200

     return '', 404

@app.route('/finishWork',  methods=['POST'])
def finishWork():
     job = request.form

     finish_jobs_queue.append((job['task_id'], job['result']))

     return '', 200


@app.route('/getWaitingQueue',  methods=['GET'])
def getWaitingQueue():
     if len(wating_jobs_queue) > 0:
          job = wating_jobs_queue[-1]
          wating_jobs_queue.pop()

          return {'job': job}, 200

     return '', 404

@app.route('/getCompleteQueue',  methods=['GET'])
def getCompleteQueue():
     return {'finish_jobs_queue': finish_jobs_queue}, 200


def spawn_worker():
     response = ec2.describe_security_groups(
          Filters=[
               dict(Name="omer-sg", Values=[group_name])
          ]
     )
     group_id = response['SecurityGroups'][0]['GroupId']

     userDataCode = f"""
     sudo echo "before update"
     sudo apt update
     sudo echo "after update"
     sudo apt install git
     sudo apt install python3 -y
     sudo pip install requests boto3
     sudo git pull git@github.com:omerdrukman/Cloud-IDC.git
     # run app
     MASTER_IP={requests.get('https://api.ipify.org').content.decode('utf8')} nohup python worker.py
     exit
     """

     instanceLst = ec2.create_instances(ImageId="ami-042e8287309f5df03",
                                        MinCount=1,
                                        MaxCount=1,
                                        KeyName="cloud-course-omer-key",
                                        UserData=userDataCode,
                                        InstanceType="t2.micro",
                                        # NetworkInterfaces=[
                                        #      {
                                        #           'SubnetId': os.environ.get('SUBNET_ID'),
                                        #           'Groups': os.environ.get('SEC_GROUP_ID'),
                                        #           'DeviceIndex': 0,
                                        #           'DeleteOnTermination': True,
                                        #           'AssociatePublicIpAddress': False,
                                        #      }
                                        # ]
                                        )


     instanceLst[0].wait_until_running()

     data = ec2.authorize_security_group_ingress(
          GroupId=security_group_id,
          IpPermissions=[
               {'IpProtocol': 'tcp',
                'FromPort': 5000,
                'ToPort': 5000,
                'IpRanges': [{'CidrIp': f'{instanceLst[0].public_ip_address}/0'}]},
          ])

     workers.append(instanceLst[0].id)

app.run('0.0.0.0', port=PORT)