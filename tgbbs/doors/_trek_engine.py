"""Vendored Star Trek (1971) game engine.

Lineage: Mike Mayfield's 1971 SDS Sigma 7 original -> Tim Holyoake's
python port (github.com/psychotimmy/trek-game) -> the sysop's telegram
port (github.com/altsoph/startrek_game_telegram_bot) -> this door.
Local changes: fixed a NameError on the low-energy branch, removed a
telegram-markdown restart hint. Everything else is left untouched,
tabs and all -- respect the elders.
"""

import random

class TrekGame(object):
	def __init__(self, test_mode=False):
		self.BUF = ""
		self.fsm_state = "init"
		pass

	def get_state(self):
		return self.fsm_state

	def tgclear(self):
		self.BUF = ""
	def tgprint(self,x="",BR=True):
		self.BUF += x
		if BR:
			self.BUF += u"\n"
	def result(self):
		return self.BUF

	def main_init(self, test_arg=None):
		self.blurb()
		# Set up a random stardate
		self.stardate=float(random.randrange(1000,1500,1))
		# Enterprise starts with 3,000 units of energy, 15 torpedoes and 1,000
		# units of energy in its shields
		self.energy=3000
		self.torpedoes=15
		self.shields=0
		# No klingons around ... yet!
		self.klingons = 0
		# The galaxy is divided into 64 sectors. Each sectoris represented by one 
		# element in the galaxy list. The galaxy list contains a three digit number
		# Hundreds = number of klingons in the sector
		# Tens = number of starbases
		# Units = number of stars
		self.galaxy=[]
		# Initialise the galaxy list
		for i in range (0,64):
			x=y=0
			z=random.randint(1,5)
			if random.randint(1,10)<8:
				x=random.randint(1,3)
			if random.randint(1,100)>88:
				y=1
			self.galaxy.append(x*100+y*10+z)
			# Keep a record of how many klingons are left to be destroyed
			self.klingons=self.klingons+x
		# Choose the starting sector and position for the Enterprise
		self.sector = random.randint(0,63)
		self.ent_position = random.randint(0,63)
		# Set up current sector and decode it
		# x = klingons; y = starbases; z = stars
		self.x,self.y,self.z=self.decode(self.galaxy[int(self.sector)])
		# Set up the current sector map
		# Each sector has 64 positions in which a klingon, starbase, star 
		# or the Enterprise may be located in
		## print("main_init",self.x,self.y,self.z,self.ent_position,self.sector,self.galaxy[int(self.sector)])
		self.current_sector=self.init(self.x,self.y,self.z,self.ent_position)
		# Perform a short range scan
		self.condition=self.srs(self.current_sector,self.ent_position)
		self.status(self.sector,self.stardate,self.condition,self.energy,self.torpedoes,self.shields,self.klingons)
		# Keep going until we have destroyed all the klingons or we run out of
		# energy or we quit

	def step(self, command="",test_arg=None, clear=True):
		if clear: self.tgclear()
		if self.fsm_state=='init':
			self.main_init()
			self.fsm_state = 'main_cmd'
		if self.fsm_state=='main_cmd':
			self.tgprint( 'Command (1-6, 0 for help)? ' )
			self.fsm_state = 'main_cmd_answer'
			return self.fsm_state
		if self.fsm_state=='helm1':
			try:
				direction = int(command)
			except:
				direction = -1
			if direction >=1 and direction <=9 and direction !=5:
				# Work out the horizontal and vertical co-ordinates # of the Enterprise in the current sector # 0,0 is top left and 7,7 is bottom right
				self.horiz=self.ent_position//8
				self.vert=self.ent_position-self.horiz*8
				# And calculate the direction component of our course vector
				self.hinc,self.vinc=self.calcvector(direction)
				# How far do we need to move?
				self.tgprint( 'Warp (1-63)? ' )
				self.fsm_state = 'helm2'
				return self.fsm_state
			else:
				self.tgprint( "That's not a direction the Enterprise can go in, captain!")
				self.fsm_state = 'main_cycle'
				return self.fsm_state
		if self.fsm_state=='helm2':
			try:
				warp = int(command)
			except:
				warp = -1
			if warp >= 1 and warp <= 63:
				# Check there is sufficient energy
				if warp <= self.energy:
					# Reduce energy by warp amount
					self.energy = self.energy - warp
					sector=self.sector
					# Remove Enterprise from current position
					self.current_sector[int(self.ent_position)] = 0
					cur_sec = self.current_sector[:]
					#cur_sec[self.ent_position] = 0
					# Calculate the new stardate
					stardate = self.stardate + (0.1*warp)
					# For the moment, assume movement leaves us in original sector
					out = False
					# Move the Enterprise warp units in the specified direction
					i=1
					while i <= warp and out == False:
						# Calculate the movement vector
						self.vert = self.vert + self.vinc
						self.horiz = self.horiz + self.hinc
						# Are we in the original sector still?
						if self.vert < 0 or self.vert > 7 or self.horiz < 0 or self.horiz > 7:
							out=True
							# Calculate new sector and join ends of the galaxy
							sector=self.join(self.sector+8*(self.horiz//8)+(self.vert//8))
						else:
							# If we are in the original sector we can't go through
							# solid objects! So reset course postion 1 click
							# Inefficient - does this for warp steps even if we
							# can't move.
							if cur_sec[int(self.vert+8*self.horiz)] != 0:
								self.vert=self.vert-self.vinc
								self.horiz=self.horiz-self.hinc
							# Put the Enterprise in the new position
							self.ent_position=self.vert+8*self.horiz
						i=i+1
					if sector == self.sector:
						# If we're still in the same sector as before, draw the Enterprise
						self.current_sector[int(self.ent_position)]=4
					else:
						# Else set up the Enterprise in the new sector
						self.sector = sector
						self.ent_position = random.randint(0,63)
						self.x,self.y,self.z=self.decode(self.galaxy[int(self.sector)])
						self.current_sector=self.init(self.x,self.y,self.z,self.ent_position)
				else:
					self.tgprint( "Too little energy left. Only "+str(self.energy)+" units remain")
					self.fsm_state = 'main_cycle'
				# Perform a short range scan after every movement
				self.condition=self.srs(self.current_sector,self.ent_position)
				if self.condition == "Docked":
					# Reset energy, torpedoes and shields
					self.energy=3000
					self.torpedoes=15
					self.shields=0
				self.status(self.sector,self.stardate,self.condition,self.energy,self.torpedoes,self.shields,self.klingons)
				self.fsm_state = 'main_cycle'
			else:
				self.tgprint( "The engines canna take it, captain!")
				self.fsm_state = 'main_cycle'
		if self.fsm_state=='phasers1':
			try:
				power = int(command)
			except:
				power = -1
			if power <= self.energy:
				# Reduce available energy by amount directed to phaser banks
				energy=self.energy-power
				# Divide phaser power by number of klingons in the sector if there are
				# any present! Space can do funny things to the mind ...
				ksec = self.x
				epos = self.ent_position
				sector = self.current_sector[:]
				shields = self.shields
				if ksec > 0:
					power=power//ksec
					# Work out the vertical and horizotal displacement of Enterprise
					horiz=epos//8
					vert=epos-(8*horiz)
					# Check all of the 64 positions in the sector for Klingons
					for i in range (0,64):
						if sector[i]<0:
							# We have a Klingon!
							# Work out its horizontal and vertical displacement
							horizk=i//8
							vertk=i-(8*horizk)
							# Work out distance from Klingon to Enterprise
							z=horiz-horizk
							y=vert-vertk
							dist=1
							while ((dist+1)*(dist+1))<(z*z+y*y):
								dist=dist+1
							# Klingon energy is negative, so add on the phaser power
							# corrected for distance
							sector[i]=sector[i]+int(power/dist)
							if sector[i]>=0:
								# Set this part of space to be empty
								sector[i]=0
								# Decrement sector klingons
								ksec=ksec-1
								self.tgprint( "Klingon destroyed!" )
							else:
								# We have a hit on Enterprise's shields if not docked
								if self.condition != "Docked":
									damage=int(power/dist)
									shields=shields-damage
									self.tgprint( "Hit on shields: "+str(damage)+" energy units")
				self.shields = shields
				self.energy = energy
				self.current_sector = sector[:]
				if ksec < self.x:
					# (x-ks) Klingons have been destroyed-update galaxy map
					self.galaxy[int(self.sector)]=self.galaxy[int(self.sector)]-(100*(self.x-ksec))
					# update total klingons
					self.klingons=self.klingons-(self.x-ksec)
					# update sector klingons
					self.x=ksec
				# Do we still have shields left?
				if self.shields < 0:
					self.tgprint( "Enterprise dead in space" )
					self.energy = 0
				else:
					self.condition=self.srs(self.current_sector,self.ent_position)
					self.status(self.sector,self.stardate,self.condition,self.energy,self.torpedoes,self.shields,self.klingons)
				self.fsm_state = 'main_cycle'
			else:
				self.tgprint( "Not enough energy, Captain!")
				self.fsm_state = 'main_cycle'
		if self.fsm_state=='torpedoes1':
			try:
				direction = int(command)
			except:
				direction = -1
			if direction >=1 and direction <=9 and direction !=5:
				torpedoes = self.torpedoes
				sector = self.current_sector[:]
				epos = self.ent_position
				ksec = self.x
				energy = self.energy

				# Work out the horizontal and vertical co-ordinates
				# of the Enterprise in the current sector
				# 0,0 is top left and 7,7 is bottom right
				horiz=epos//8
				vert=epos-horiz*8
				# And calculate the direction to fire the torpedo
				hinc,vinc=self.calcvector(direction)
				# A torpedo only works in the current sector and stops moving
				# when we hit something solid
				out = False
				while out == False:
					 # Calculate the movement vector
					vert = vert + vinc
					horiz = horiz + hinc
					# Is the torpedo still in the sector?
					if vert < 0 or vert > 7 or horiz < 0 or horiz > 7:
						out=True
						self.tgprint( "Torpedo missed")
					else:
						# Have we hit an object?
						if sector[int(vert+8*horiz)] == 2:
							# Oh dear - taking out a starbase ends the game
							out=True
							sector[int(vert+8*horiz)] = 0
							energy=0
							self.tgprint( "Starbase destroyed")
						elif sector[int(vert+8*horiz)] == 3:
							# Shooting a torpedo into a star has no effect
							out=True
							self.tgprint( "Torpedo missed")
						elif sector[int(vert+8*horiz)] < 0:
							# Hit and destroyed a Klingon!
							out=True
							sector[int(vert+8*horiz)] = 0
							ksec = ksec - 1
							self.tgprint( "Klingon destroyed!")
				# One fewer torpedo
				torpedoes = torpedoes-1

				self.torpedoes = torpedoes
				self.energy = energy
				self.current_sector = sector[:]
				# A Klingon has been destroyed-update galaxy map
				if ksec < self.x:
					self.galaxy[int(self.sector)]=self.galaxy[int(self.sector)]-100
					# update total klingons
					self.klingons=self.klingons-(self.x-ksec)
					# update sector klingons
					self.x=ksec
				self.condition=self.srs(self.current_sector,self.ent_position)
				self.status(self.sector,self.stardate,self.condition,self.energy,self.torpedoes,self.shields,self.klingons)
				self.fsm_state = 'main_cycle'
			else:
				self.tgprint( "Your command is not logical, Captain.")
				self.fsm_state = 'main_cycle'

		if self.fsm_state=='shields1':
			try:
				power = int(command)
			except:
				power = -1
			if ((power > 0) and (self.energy >= power)):
				self.energy = self.energy - power
				self.shields = self.shields + power
			self.condition=self.srs(self.current_sector,self.ent_position)
			self.status(self.sector,self.stardate,self.condition,self.energy,self.torpedoes,self.shields,self.klingons)
			self.fsm_state = 'main_cycle'

		if self.fsm_state=='main_cmd_answer':
			if command == "0":
				self.showhelp()
				# return self.main_step('main_cmd',"")
			elif command == "1":
				self.tgprint( 'Course direction(1-9)? ' )
				self.fsm_state = 'helm1'
				return self.fsm_state
			elif command == "2":
				self.lrs(self.galaxy,self.sector)
				self.fsm_state = 'main_cycle'
			elif command == "3":
				self.tgprint( 'Phaser energy? ' )
				self.fsm_state = 'phasers1'
				return self.fsm_state
			elif command == "4":
				if self.torpedoes < 1:
					self.tgprint( 'No photon torpedoes left, captain! ' )
					self.fsm_state = 'main_cycle'
				else:
					self.tgprint( 'Fire in direction(1-4,6-9)? ' )
					self.fsm_state = 'torpedoes1'
					return self.fsm_state
			elif command == "5":
				self.tgprint( 'Energy to shields? ' )
				self.fsm_state = 'shields1'
				return self.fsm_state

			elif command == "6":
				# Set quit condition by making energy = 0
				self.energy = 0

			else:
				self.tgprint( "Command not recognised captain")

		if self.fsm_state=='main_cycle':
			self.fsm_state = 'main_cmd'
			if self.condition == "Red" and command != 0:
				if random.randint(1,9)<6:
					self.tgprint( "Red alert - Klingons attacking!")
					self.damage=self.x*random.randint(1,50)
					self.shields=self.shields-self.damage
					self.tgprint( "Hit on shields: "+str(self.damage)+" energy units")
					# Do we still have shields left?
					if self.shields < 0:
						self.tgprint( "Enterprise dead in space")
						self.energy = 0
					else:
						self.condition=self.srs(self.current_sector,self.ent_position)
						self.status(self.sector,self.stardate,self.condition,self.energy,self.torpedoes,self.shields,self.klingons)
		# if test_arg is not None:
		# 	break # bail out of loop after one pass during testing
		if self.klingons == 0 or self.energy == 0: 
			if self.klingons == 0:
				# self.promotion()
				self.tgprint( "\nYou have successfully completed your mission!")
				self.tgprint( "The federation has been saved.")
				self.tgprint( "You have been promoted to Admiral Kirk.")
			else:
				self.tgprint( "\nYou are relieved of duty.")				
			self.tgprint( "\n      GAME OVER")
			self.tgprint( "```\n*Type* /start *or anything else to start again*\n```")
			self.fsm_state = 'init'
			return self.fsm_state
		self.fsm_state = 'main_cmd'
		return self.fsm_state
		
	def status(self,sector,stardate,condition,energy,torpedoes,shields,klingons):
		self.tgprint( "\nStardate:		   "+str(stardate ))
		self.tgprint( "Condition:		  "+str(condition))
		self.tgprint( "Energy:			 "+str(energy))
		self.tgprint( "Photon torpedoes:   "+str(torpedoes))
		self.tgprint( "Shields:			"+str(shields ))
		self.tgprint( "Klingons in galaxy: "+str(klingons)+"\n")
	 
	def blurb(self):
		self.tgprint( "\nSpace ... the final frontier.")
		self.tgprint( "These are the voyages of the starship Enterprise")
		self.tgprint( "Its five year mission ...")
		self.tgprint( "... to boldly go where no-one has gone before")
		self.tgprint( "You are Captain Kirk. Your mission is to destroy\nall of the Klingons in the galaxy.")
		
	def decode(self, sector):
		# Hundreds = klingons, tens = starbases, units = stars
		klingons=int(round(float(sector)/100.))
		starbases=int(round(float(sector-klingons*100)/10))
		stars=sector-klingons*100-starbases*10
		## print("decode",sector,klingons,starbases,stars)
		return(klingons,starbases,stars)

	def init(self,klingons,bases,stars,eposition):
		## print("init",klingons,bases,stars,eposition)
		current_sector=[]
		for j in range (0,64):
			current_sector.append(0)
		# A value of 4 in the sector map indicates the Enterprise's position
		current_sector[eposition]=4
		# Add in the stars (value = 3)
		while stars > 0:
			position = random.randint(0,63)
			if current_sector[position]==0:
				current_sector[position]=3
				stars=stars-1
		# Add in the starbases (value = 2)
		while bases > 0:
			position=random.randint(0,63)
			if current_sector[position]==0:
				current_sector[position]=2
				bases=bases-1
		# Add in the klingons (value = -200)
		while klingons > 0:
			position=random.randint(0,63)
			if current_sector[position]==0:
				current_sector[position]=-200
				klingons=klingons-1
		return(current_sector)
		
	def srs(self,current_sector,ent_pos):
		# Print out sector map
		# Key: >!< = Klingon
		#	  <O> = Starbase
		#	   *  = Star
		#	  -O- = Enterprise
		klingons=False
		for i in range (0,64):
			if i%8 == 0:
				self.tgprint()
			if current_sector[i]<0:
				klingons=True
				self.tgprint( ">!<", False )
			elif current_sector[i]==0:
				self.tgprint( " . ", False )
			elif current_sector[i]==2:
				self.tgprint( "<O>", False )
			elif current_sector[i]==3:
				self.tgprint( " * ", False )
			else:
				self.tgprint( "-O-", False )
		self.tgprint()
		# Work out condition
		if klingons == False:
			condition="Green"
		else:
			condition="Red"
		# But docked status overrides Red/Green
		port=ent_pos-1
		starboard=ent_pos+1
		if port >= 0:
			if current_sector[int(port)]==2:
				condition="Docked"
		if starboard <= 63:
			if current_sector[int(starboard)]==2:
				condition="Docked"
		# Return condition status
		return(condition)
		
	def lrs(self, galaxy,sector):
		# Print out the klingons/starbase/stars values from the
		# neighbouring eight sectors (and this one)
		self.tgprint()
		for i in range (-8,9,8):
			for j in range (-1,2):
				# Join the ends of the galaxy together
				sec=self.join(sector+j+i)
				if not i and not j:
					self.tgprint( "[%03d]" % galaxy[int(sec)], False )
				else:
					self.tgprint( " %03d " % galaxy[int(sec)], False )
			self.tgprint()
		self.tgprint()

	def calcvector(self, direction):
		# Convert numeric keypad directions to that of the original game
		# NK 7 = 7 / # NK 4 = 6 / # NK 1 = 5 / # NK 2 = 4
		# NK 3 = 3 / # NK 6 = 2 / # NK 9 = 1 / # NK 8 = 0
		# This could be rather more elegant if I didn't bother doing this!
		# However, I'm trying to stay true to the spirit of the original
		# BASIC listing ...
		if direction == 4:
			direction = 6
		elif direction == 1:
			direction = 5
		elif direction == 2:
			direction = 4
		elif direction == 6:
			direction = 2
		elif direction == 9:
			direction = 1
		elif direction == 8:
			direction = 0
		# Work out the direction increment vector
		# hinc = horizontal increment
		# vinc = vertical increment
		if direction < 2 or direction > 6:
			hinc = -1
		elif direction > 2 and direction < 6:
			hinc = 1
		else:
			hinc = 0
		if direction < 4 and direction > 0:
			vinc = 1
		elif direction > 4:
			vinc = -1
		else:
			vinc = 0
		return(hinc,vinc)
		
	def join(self, sector):
		# Join the ends of the galaxy together
		if sector < 0:
			sector = sector + 64
		if sector > 63:
			sector = sector - 63
		return(sector)

	def showhelp(self):
		# Print out the command help
		self.tgprint( "1 - Helm")
		self.tgprint( "2 - Long Range Scan")
		self.tgprint( "3 - Phasers")
		self.tgprint( "4 - Photon Torpedoes")
		self.tgprint( "5 - Shields")
		self.tgprint( "6 - Resign")
	
