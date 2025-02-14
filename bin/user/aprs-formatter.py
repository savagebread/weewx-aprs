from datetime import datetime
import os

import weeutil.weeutil
import weewx.engine
import weewx.units
import logging


class APRS(weewx.engine.StdService):
    def __init__(self, engine, config_dict):
        super(APRS, self).__init__(engine, config_dict)
        conf = config_dict['APRS']
        self._output_filename = conf['output_filename']
        self._output_filename_tmp = self._output_filename + '.tmp'
        self._include_position = int(conf.get('include_position', 0))
        self._symbol_table = conf.get('symbol_table', '/')
        self._symbol_code = conf.get('symbol_code', '_')
        self._comment = conf.get('comment', '')
        self._stationModel = conf['station_model']
        self._reportLuminosity =  int(conf.get('report_luminosity', 0))

        self._message_type = '_'  # Weather report (no position)
        self._time_format = '%m%d%H%M'
        self._latitude = None
        self._longitude = None
        
        # Accurite model 01036 seems to require these markers with no timestamp
        if "accurite" in self._stationModel:
            self._wind_direction_marker = ''
            self._wind_direction_marker = '/'
        else:
            self._wind_direction_marker = 'c'
            self._wind_speed_marker = 's'
        
        if self._include_position:
            # Position with timestamp (no APRS messaging)
            self._message_type = '/'
            self._time_format = '%d%H%Mz'
            self._latitude = ''.join(weeutil.weeutil.latlon_string(
                self.engine.stn_info.latitude_f,
                ('N', 'S'), 'lat'))
            self._longitude = ''.join(weeutil.weeutil.latlon_string(
                self.engine.stn_info.longitude_f,
                ('E', 'W'), 'lon'))
            self._wind_direction_marker = ''
            self._wind_speed_marker = '/'

        self.bind(weewx.NEW_ARCHIVE_RECORD, self._handle_new_archive_record)

    def _handle_new_archive_record(self, event):
        """Generate a positionless APRS weather report and write it to a file"""
        
        record = event.record
        # Accurite Model 01036 seems to require timestamp be removed
        if "accurite" in self._stationModel:
             data = [self._message_type,'']
        else:
            data = [
                self._message_type,
                datetime.strftime(
                    datetime.utcfromtimestamp(record['dateTime']),
                    self._time_format),
            ]
            
        if self._include_position:
            data.append(self._latitude)
            data.append(self._symbol_table)
            data.append(self._longitude)
            data.append(self._symbol_code)

        if record.get('windDir') is not None:
            # Wind direction (in degrees)
            # Wind from North needs to be reported as 360.
            # Wind from 0 means N/A in the APRS standard.
            # We need to make sure it does not get to 0, so do not rely on
            # the format string rouding, but round to no decimals before
            # comparing with 0
            wind_dir = int(round(record['windDir'], 0))
            if wind_dir <= 0:
                wind_dir = 360
            try: 
                data.append('%s%03u' % (self._wind_direction_marker,
                                    wind_dir))
            except Exception as e:
                logging.error("weewx-aprs-packet-formatter - %s %s %s" % (e, self._wind_direction_marker,
                                    wind_dir))
        else:
            data.append('%s...' % self._wind_direction_marker)

        if record.get('windSpeed') is not None:
            try: 
                data.append('%s%03.f' % (self._wind_speed_marker,
            record['windSpeed']))
            except Exception as e:
                logging.error("weewx-aprs-packet-formatter - windSpeed -  %s %s %s" % (e, self._wind_speed_marker,
            record['windSpeed']))
        else:
            data.append('%s...' % self._wind_speed_marker)

        if record.get('windGust') is not None:
            # Gust (peak wind speed in mph in the last 5 minutes)
            try: 
                data.append('g%03.f' % record['windGust'])
            except Exception as e:
                logging.error("weewx-aprs-packet-formatter - windGust - %s" % (e))
                data.append('g...')
        else:
            data.append('g...')

        if record.get('outTemp') is not None:
            # Temperature (in degrees Fahrenheit)
            try: 
                data.append('t%03.f' % record['outTemp'])
            except Exception as e:
                data.append('t...')
        else:
            data.append('t...')

        if record.get('rainRate') is not None:
            # Rainfall (in hundredths of an inch) in the last hour
            try: 
                data.append('r%03.f' % (record['rainRate'] * 100))
            except Exception as e:
                logging.error("weewx-aprs-packet-formatter - rainRate - %s %s %s"% (e, record['rainRate'] * 100))

        if record.get('daily_rain') is not None:
            # Rainfall (in hundredths of an inch) since midnight
            try: 
                data.append('P%03.f' % (record['dayRain'] * 100))
            except Exception as e:
                logging.error("weewx-aprs-packet-formatter - dayrain - %s %s %s" % (e, record['dayRain'] * 100))

        if record.get('outHumidity') is not None:
            # Humidity (in %. 00 = 100%)
            # We need to make sure it does not get over 99, so do not rely on
            # the format string rouding, but round to no decimals before
            # comparing with 100
            humidity = int(round(record['outHumidity'], 0))
            if humidity >= 100:
                humidity = 0
            try:
                data.append('h%02u' % humidity)
            except Exception as e: 
                logging.error("weewx-aprs-packet-formatter - humidity - %s %s" % (e, humidity))
        if record.get('barometer') is not None:
            # Barometric pressure (in tenths of millibars/tenths of hPascal)
            barometer = weewx.units.convert(
                (record['barometer'], 'inHg', 'pressure'),
                'mbar')[0] * 10
            try:
                data.append('b%05.f' % barometer)
            except:
                logging.error("weewx-aprs-packet-formatter - barometer - %s" % (barometer))
        
        if self._reportLuminosity == 1:
            if record.get('luminosity') is not None:
                #Luminosity in watts per meter ^2, 3 places
                try:
                    lumen = record['luminosity']
                    data.append('L%03.u' % lumen)
                except Exception as e:
                    logging.error("weewx-aprs-packet-formatter - luminosity - %s" % (e))

        if self._comment:
            data.append(self._comment)

        wxdata = ''.join(data)

        # Atomic update of self._output_filename.
        with open(self._output_filename_tmp, 'w') as f:
            f.write(wxdata)
            logging.info("weewx-aprs-packet-formatter - %s"% (wxdata))
        os.rename(self._output_filename_tmp, self._output_filename)
