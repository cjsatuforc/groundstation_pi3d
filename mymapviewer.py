#!/usr/bin/python
from __future__ import absolute_import, division, unicode_literals
from os.path import abspath, dirname
from math import ceil
from datetime import datetime
from gui.Pointer import Pointer
from gui.crosshair import Crosshair
from gui.textWidget import TextWidget
import pi3d

from tileLoader import TileLoader
from gui.horizon.horizon import Horizon
from comm import TelemetryReader


WHERE_AM_I = abspath(dirname(__file__))
flat_shader = pi3d.Shader("uv_flat")

class GroundStation(object):

        def __init__(self, width=-1, height=-1):
            ### starting display, and 3d part###
            self.display = pi3d.Display.create(x=0, y=0, w=width, h=height,
                                               frames_per_second=20,
                                               background=(0, 0, 0, 255))
            pi3d.Light((0, 0, 10))
            self.shader = pi3d.Shader("uv_flat")

            self.camera = pi3d.Camera(is_3d=False)
            self.camera.was_moved = False

            self.text = TextWidget(self.display,self.camera)
            self.text.set_update_rate(3) #update every 3 seconds

            self.flat_shader = pi3d.Shader("uv_flat")

            #starting input listeners#
            self.inputs = pi3d.InputEvents()
            self.inputs.get_mouse_movement()

            self.width = self.display.width
            self.height = self.display.height

            self.last_scroll = datetime.now()    # variable to limit zooming speed

            self.window = self.display

            # these are the point where the screen focuses
            self.view_longitude = -48.519688
            self.view_latitude = -27.606899

            #additional points showing on the map
            self.points = [(self.view_longitude, self.view_latitude),
                           (0.0, 0.0),
                           (180, 36.8),
                           (-47.886829, -15.793751)]

            # this will show as an arrow on the map
            self.tracked_object_position = [0, 0, 0]
            self.tracking = True

            #camera should follow tracked object?
            self.following_tracked = True

            #current zoom level
            self.zoom = 10
            #current button state
            self.button = 0

            # mouse coordinates on screen
            self.pointer_x = 0
            self.pointer_y = 0

            # position variations on a "tick"
            self.dx = 0
            self.dy = 0

            #currently loaded tiles
            self.tiles = []
            self.tiles_set = set()
            self.current_center_tile = (0, 0)

            #draw gui only, the avoid redrawing the tiles
            self.draw_gui_only_flag = False

            #should reload the tiles? set on moving the map
            self.updated = True
            self.tile_list_updated = True

            self.crosshair = Crosshair(self.display, self.camera)

            self.waypoint_img = pi3d.Texture("textures/crosshair4040.png", blend=True)
            self.waypoint_sprite = pi3d.Sprite(camera=self.camera, w=20, h=20, x=0, y=0, z=0.1)
            self.waypoint_sprite.set_draw_details(self.flat_shader, [self.waypoint_img], 0, 0)
            self.waypoint_sprite_list = []

            tracked_img = pi3d.Texture("textures/gpspointer6060.png", blend=True)
            self.tracked_sprite = pi3d.Sprite(camera=self.camera, w=60, h=60, x=0, y=0, z=10)
            self.tracked_sprite.rotateToY(0)
            self.tracked_sprite.rotateToX(0)
            self.tracked_sprite.rotateToZ(0)
            self.tracked_sprite.set_draw_details(self.flat_shader, [tracked_img], 0, 0)
            self.tracked_sprite.scale(0.8, 0.8, 0.8)

            self.info_sprite = pi3d.Sprite(camera=self.camera, w=100, h=100, x=0, y=0, z=0.1)


            self.display.add_sprites(self.tracked_sprite)
            #the tile loader gives the tiles around the current position
            self.tile_loader = TileLoader(self)

            #shows the navball
            self.horizon = Horizon(self.camera, self.display)
            #shows the mouse pointer
            self.pointer = Pointer(self)
            #reads telemetry from the serial port
            self.telemetry_reader = TelemetryReader(self)
            self.data = {}
            self.main_loop()

        def zoom_in(self):
            self.zoom += 1
            if self.zoom > 20:
                self.zoom = 20

        def zoom_out(self):
            self.zoom -= 1
            if self.zoom < 2:
                self.zoom = 2

        def on_scroll(self, zoom_in):
            if (datetime.now() - self.last_scroll).microseconds > 100000:
                if zoom_in > 0:
                    self.zoom_in()
                elif zoom_in < 0:
                    self.zoom_out()
                self.queue_draw(tile=True)
                self.last_scroll = datetime.now()
                print(self.zoom)

        def set_zoom(self, zoom):
            self.zoom = zoom

        def set_focus(self, longitude, latitude):
            self.view_longitude = longitude
            self.view_latitude = latitude
            self.queue_draw(tile=True)


        def draw_circle_at(self, x_pos, y_pos):
            """draws a circle centered at (x_pos,y_pos)"""
            self.waypoint_sprite.position(x_pos, -y_pos, 0.1)
            self.waypoint_sprite.draw()

        #@timeit
        def draw_info(self):
            """
            draws text data on the screen, currently, gps data and pending tiles to draw

            usually takes 1~5ms
            250ms when updating!
            """
            string = " lat:{0}\n long:{1}".format(self.view_latitude, self.view_longitude)
            self.text.set_text(string)
            self.text.update()

        #@timeit
        def draw_points(self):
            """
            draws each of the self.points on the screen as circles
            """

            if self.updated:
                number_of_points = len(self.points)
                if number_of_points != len(self.waypoint_sprite_list):
                    for i in range(number_of_points):
                        sprite = pi3d.Sprite(camera=self.camera, w=20, h=20, x=0, y=0, z=1)
                        sprite.set_draw_details(self.flat_shader, [self.waypoint_img], 0, 0)
                        self.waypoint_sprite_list.append(sprite)
                    self.display.add_sprites(*self.waypoint_sprite_list)
                for point, sprite in zip(self.points, self.waypoint_sprite_list):
                    x, y = self.tile_loader.dcord_to_dpix(point[0],
                                                          self.view_longitude,
                                                          point[1],
                                                          self.view_latitude,
                                                          self.zoom)
                    sprite.position(x, -y, 10)

        #@timeit
        def draw_tracked_object(self):
            """
            draws the tracked object on its position, with proper orientation, as an arrow

            takes ~0ms
            """
            if self.tracking:
                point = self.tracked_object_position
                x, y = self.tile_loader.dcord_to_dpix(point[0],
                                                      self.view_longitude,
                                                      point[1],
                                                      self.view_latitude,
                                                      self.zoom)
                self.tracked_sprite.position(x, -y, 1)
                self.tracked_sprite.rotateToZ(-point[2])
                self.tracked_sprite.draw()

        def set_tracked_position(self, longitude, latitude, yaw):
            """
            updates tracked object position, called by telemetry reader
            """
            if self.tracked_object_position[0] != longitude or self.tracked_object_position[1] != latitude:
                self.tracked_object_position = (longitude, latitude, yaw)
                #asks to update the gui alone
                self.queue_draw(gui_only=True)

            if self.following_tracked and "gps_sats" in self.data:
                if self.data["gps_sats"] >= 3:
                    self.set_focus(longitude, latitude)
                    self.queue_draw(tile=True)

        def set_attitude(self, roll, pitch, yaw=0):
            """
            updates the object attitude, called from telemetry reader, written directly on self.horizon.
            should probably be changed
            """
            if self.horizon.tilt != pitch or self.horizon.roll != roll or self.horizon.yaw != yaw:
                self.horizon.set_attitude(roll, pitch, yaw)
                self.queue_draw(gui_only=True)

        def draw_tiles(self):
            """
            Core map-drawing function

            checks if the map position has been updated, if not, prints the old tiles.
            if so, reloads the tiles as a bidimensional list, and prints them accordingly
            """
            span_x = self.width
            span_y = self.height
            tiles_x = int(ceil(span_x/256.0))
            tiles_y = int(ceil(span_y/256.0))
            if self.updated:
                # checks if the centered tile changed, so the tile set has to be reloaded
                new_center_tile = self.tile_loader.coord_to_gmap_tile_int(self.view_longitude,
                                                                          self.view_latitude,
                                                                          self.zoom)

                if new_center_tile != self.current_center_tile or self.tile_list_updated:
                    new_tiles = self.tile_loader.load_area(self.view_longitude,
                                                           self.view_latitude,
                                                           self.zoom,
                                                           tiles_x,
                                                           tiles_y)
                    ## using sets to detect sprites to be loaded and unloaded
                    new_set = set()
                    for line in new_tiles:
                        new_set |= set(line)

                    removing = self.tiles_set-new_set
                    self.display.remove_sprites(*removing)

                    adding = new_set - self.tiles_set
                    self.display.add_sprites(*adding)
                    self.tiles = new_tiles
                    self.tiles_set = new_set     # updated curren tiles

                self.current_center_tile = new_center_tile

                # tiles have been properly loaded, now we have to place them on the proper positions

                tile_number = 0
                line_number = 0
                x_center = 0
                y_center = 0
                ## offset to keep the current coordinate centered on the screen
                offset_x, offset_y = self.tile_loader.gmap_tile_xy_from_coord(self.view_longitude,
                                                                              self.view_latitude,
                                                                              self.zoom)

                #size of lines and columns
                x_tiles = len(self.tiles[0])
                y_tiles = len(self.tiles)

                #draw it all, fixing the position
                for line in self.tiles:
                    for tile in line:
                        x = (tile_number - int(x_tiles/2)) * 256 + x_center
                        y = (line_number - int(y_tiles/2)) * 256 + y_center
                        final_x = x - offset_x + 128
                        final_y = y - offset_y + 128
                        tile.position(final_x+self.dx, -(final_y+self.dy), 100.0)
                        #tile.draw()
                        tile_number += 1
                    tile_number = 0
                    line_number += 1

                self.draw_points()  # must move out of here!
                self.updated = False
            else:
                pass

        def draw(self):
            """
            high level draw function, calls the lower ones
            """
            self.draw_tiles()
            self.draw_gui()

        #@timeit
        def draw_gui(self):
            if self.draw_gui_only_flag:
                self.draw_tracked_object()  # 0ms
                self.draw_instruments()     # 0ms
                #draws mouse pointer
                self.pointer.update()
                self.draw_info()            # 5ms

        #@timeit
        def draw_instruments(self):
            """
            draws navball
            takes ~0ms
            """
            self.horizon.update()

        def queue_draw(self, gui_only=False, tile=False):
            """
            schedules a draw on next tick, may be complete, or gui-only
            """
            self.updated = not gui_only
            self.draw_gui_only_flag = True
            self.tile_list_updated = tile

        def update_mouse(self):
            """
            process mouse state
            """
            self.inputs.do_input_events()
            imx, imy, zoom, imh, imd = self.inputs.get_mouse_movement()
            self.pointer.on_move(self.pointer_x+imx, self.pointer_y+imy)

            if self.button == 1:
                delta_longitude, delta_latitude = self.tile_loader.dpix_to_dcoord(imx, self.view_latitude, imy, self.zoom)
                self.view_longitude -= delta_longitude
                self.view_latitude -= delta_latitude
                self.queue_draw()

               #check map boundaries
                if self.view_longitude > 180:
                    self.view_longitude = 180.0
                if self.view_longitude < -180:
                    self.view_longitude = -180.0
                if self.view_latitude > 85.0:
                    self.view_latitude = 85.0
                if self.view_latitude < -85.0:
                    self.view_latitude = -85.0
                #asks for update
                self.queue_draw()

            if self.inputs.key_state("BTN_LEFT"):
                self.button = 1
            else:
                self.button = 0
            if zoom:
                self.on_scroll(zoom)

        def set_data(self, string, value):
            self.data[string] = value

        def main_loop(self):
            """
            This is the Main Loop of the Game
            checks for mouse and keyboard inputs,
            draws the screen,
            and quits, if esc is pressed
            """
            time = 0
            start_time = datetime.now()
            while self.display.loop_running():
                self.update_mouse()
                if self.inputs.key_state(27):
                    self.display.destroy()
                    self.tile_loader.run = False
                    self.telemetry_reader.run = False
                self.draw()
                new_time = datetime.now()
                time = ((new_time-start_time).microseconds/1000000.0) * 0.1 + time*0.9
                print "frame took {0:.2f} avg: {1:.2f} , fps:{2:.2f}".format(((new_time-start_time).microseconds/1000000.0), time, 1.0/time)
                start_time = new_time

if __name__ == '__main__':
    gui = GroundStation()
