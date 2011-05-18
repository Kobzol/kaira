#
#    Copyright (C) 2010, 2011 Stanislav Bohm
#
#    This file is part of Kaira.
#
#    Kaira is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, version 3 of the License, or
#    (at your option) any later version.
#
#    Kaira is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Kaira.  If not, see <http://www.gnu.org/licenses/>.
#

import xml.etree.ElementTree as xml
import process
import utils
import random
from project import load_project_from_xml
from events import EventSource

class SimulationException(Exception):
	pass

class Simulation(EventSource):
	"""
		Events: changed, inited, error, shutdown
	"""

	controller = None
	project = None
	process_count = None
	quit_on_shutdown = False

	def __init__(self):
		EventSource.__init__(self)
		self.random = random.Random()

	def connect(self, host, port):
		def connected(stream):
			self.controller = controller
			self.read_header(stream)
			self.query_reports(lambda: self.emit_event("inited"))
		connection = process.Connection(host, port, exit_callback = self.controller_exit, connect_callback = connected)
		controller = process.CommandWrapper(connection)
		controller.start()

	def controller_exit(self, message):
		if message:
			self.emit_event("error", message + "\n")

		if self.controller:
			self.emit_event("error", "Traced process terminated\n")

		self.controller = None

	def shutdown(self):
		if self.controller:
			if self.quit_on_shutdown:
				self.controller.run_command("QUIT", None)
			else:
				self.controller.run_command("DETACH", None)
		self.controller = None
		self.emit_event("shutdown")

	def get_net(self):
		return self.project.net

	def read_header(self, stream):
		header = xml.fromstring(stream.readline())
		lines_count = int(header.get("description-lines"))
		project_string = "\n".join((stream.readline() for i in xrange(lines_count)))
		self.project = load_project_from_xml(xml.fromstring(project_string), "")

	def query_reports(self, callback = None):
		def reports_callback(line):
			root = xml.fromstring(line)
			self.units = [ Unit(e) for e in root.findall("unit") ]
			self.instances = {}
			for u in self.units:
				if not self.instances.has_key(u.path):
					self.instances[u.path] = NetworkInstance(u.path)
				self.instances[u.path].add_unit(u)
			if callback:
				callback()
			self.emit_event("changed")
		self.controller.run_command("REPORTS", reports_callback)

	def fire_transition(self, transition, iid):
		if self.controller:
			self.controller.run_command_expect_ok("FIRE " + str(transition.get_id()) + " " + str(iid))
			self.query_reports()

	def fire_transition_random_instance(self, transition):
		enabled_iids = self.enabled_instances_of_transition(transition)
		if len(enabled_iids) > 0:
			iid = self.random.choice(enabled_iids)
			self.fire_transition(transition, iid)

	def running_paths(self):
		return self.instances.keys()

	def get_instance(self, path):
		return self.instances[path]

class Path:
	def __init__(self, items, absolute = True):
		self.items = tuple(items)
		self.absolute = absolute

	def __eq__(self, path):
		return self.absolute == path.absolute and self.items == path.items

	def __hash__(self):
		return hash(self.items)

	def __str__(self):
		start = "/" if self.absolute else "./"
		return start + "/".join(map(str,self.items))

def path_from_string(string):
    assert string != ""
    if string[-1] == "/":
        string = string[:-1]
    items = string.split("/")
    if items[0] == "":
        return Path(map(int, items[1:]))
    elif items[0] == ".":
        return Path(map(int, items[1:]), False)
    else:
        return Path(map(int, items), False)

class Unit:

	def __init__(self, unit_element):
		self.places = {}
		self.path = path_from_string(unit_element.get("path"))
		for place in unit_element.findall("place"):
			tokens = [ e.get("value") for e in place.findall("token") ]
			self.places[int(place.get("id"))] = tokens

	def has_place(self, place):
		return self.places.has_key(place.get_id())

	def get_tokens(self, place):
		return self.places[place.get_id()]

class NetworkInstance:

	def __init__(self, path):
		self.path = path
		self.units = []

	def add_unit(self, unit):
		self.units.append(unit)

	def get_tokens(self, place):
		for u in self.units:
			if u.has_place(place):
				return u.get_tokens(place)
		return None
