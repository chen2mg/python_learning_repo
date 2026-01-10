# python_learning_repo
Jupyter Notebooks for 10-year-old kids learning Python to control VEX IQ robots via Raspberry Pi.

## 🛠 1. Initial System Setup
Run these commands once to make sure the Raspberry Pi can be found on the network by its name instead of an IP address.

### Install Networking Tools
```bash
sudo apt update
sudo apt install avahi-daemon -y
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
```

Set the Custom Server Name
To change the address from raspberrypi.local to myjupyterlab.local, run:
```bash
sudo hostnamectl set-hostname myjupyterlab
```
Note: After running this, reboot your Pi for changes to take effect: sudo reboot

## 🚀 2. Run the Server
We use Docker to run Jupyter Lab. Make sure you are inside the python_learning_repo folder.

To start the server:
```bash
make up
```
To stop the server:
```bash
make down
```

## 🌐 3. Access Jupyter Lab
Once the Pi is running and connected to your Wi-Fi, open a web browser on any computer and go to:

# http://raspberrypi.local
or
# http://myjupyterlab.local
Login Password: 1234

(Note: You do not need to type :8888 if you updated your docker-compose ports to "80:8888")

