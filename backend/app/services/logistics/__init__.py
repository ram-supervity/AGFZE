"""Shipment and cargo tracking - the module added in .

Split three ways on purpose. `adapters` is the seam a carrier integration would plug into and is
deliberately empty of concrete implementations. `shipment_service` reads and creates. And
`tracking_service` is the orchestration that walks whatever adapters exist, applies whatever they
or a person report through one shared path, and ages a shipment nobody has heard from into the
exception queue that already exists.
"""
