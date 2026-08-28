Geocoding
=========

Convert addresses into GPS coordinates, and coordinates back into place names,
through a pluggable provider.

Configure
---------
You can configure in General Settings the default provider of the geocoding API service.

A method `_call_<service>` should be implemented in object `geocoder` that accepts an address string as parameter and return (latitude, longitude) tuple for this to work.
If no default provider is set, the first one will be used by default.

An optional method `_geo_query_address_<service>` which takes address fields as parameters can be defined to encode the query string for the provider.
